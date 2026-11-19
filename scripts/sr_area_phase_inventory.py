"""Inventory each actual round-eight final map and its own case-one activity."""
from pathlib import Path
import argparse,json,re
from ffn_sr_area import ROOT,REPORT,dump,review_group

def saif_index(path):
    text=re.sub(r'/\*[\s\S]*?\*/','',path.read_text())
    tokens=iter(re.findall(r'"[^"]*"|\(|\)|[^\s()]+',text));stack=[];tree=[]
    for token in tokens:
        if token=='(':
            node=[]
            if stack:stack[-1].append(node)
            else:tree=node
            stack.append(node)
        elif token==')':stack.pop()
        else:stack[-1].append(token)
    activity={}
    def walk(node,path=''):
        if not isinstance(node,list) or not node:return
        if node[0]=='INSTANCE':
            path=(path+'/'+node[1].strip('"')).strip('/')
            for child in node[2:]:walk(child,path)
        elif node[0] in ['NET','PORT']:
            for sig in node[1:]:
                if isinstance(sig,list):activity[(path+'/'+sig[0]).replace('\\','')]=dict((p[0],float(p[1])) for p in sig[1:] if isinstance(p,list))
        else:
            for child in node:walk(child,path)
    walk(tree);prefix='complete_soc_tb/dut/'
    return {k[len(prefix):]:v for k,v in activity.items() if k.startswith(prefix)},re.search(r'\(DURATION ([^)]+)',text).group(1)

def inventory(name):
    state=json.loads((REPORT/(name+'.json')).read_text());profile=json.loads((ROOT/state['profile']).read_text())
    mapped=ROOT/'build/server'/('complete_soc_sm40_'+profile['tag']);text=(mapped/'netlist.v').read_text()
    modules={m.group(1):m.group(2) for m in re.finditer(r'module\s+(\w+)\s*\(([\s\S]*?)endmodule',text)}
    instances={mod:[(m.group(1),m.group(2),dict(re.findall(r'\.(\w+)\s*\(([^()]*)\)',m.group(3)))) for m in re.finditer(r'^\s*(\w+)\s+(\S+)\s*\(([\s\S]*?)\);',body,re.M)] for mod,body in modules.items()}
    hierarchy={};cells={}
    def descend(mod,path=''):
        hierarchy[path]=mod
        for ref,inst,pins in instances[mod]:
            full=(path+'/'+inst).strip('/');cells[full]=dict(ref=ref,pins=pins,parent_module=mod)
            if ref in modules:descend(ref,full)
    descend('kwt_complete_soc')
    mappings=[]
    for line in (mapped/'saif_map.tcl').read_text().splitlines():
        m=re.search(r'-rtl \{([^}]+)\} -gate (.*)',line)
        if m:
            gate=re.search(r'\{([^}]+)\}',m.group(2)).group(1)
            mappings.append(dict(rtl=m.group(1),gate=gate,cell='get_cell' in m.group(2),inverted=line.rstrip().endswith('-inverted')))
    activity,duration=saif_index(ROOT/'reports/optimization/complete_soc'/name/'activity_01.saif')
    targets=[];seen=set()
    def target(kind,value):
        key=(kind,value)
        if key not in seen:seen.add(key);targets.append(dict(kind=kind,name=value))
    for row in mappings:
        if row['cell'] and row['inverted']:
            cell=cells[row['gate']]
            for pin in ['D','Q','QN']:
                if pin in cell['pins']:target('pin',row['gate']+'/'+pin)
        elif not row['cell']:
            rtl=row['rtl'];core='/accelerator/controller/core/' in rtl
            interface=('shared_memory/' in rtl or '/dma_frontend/' in rtl or 'sysmem_icb_' in rtl)
            if core or (interface and re.search(r'valid|ready|read|write|reset|rst|enable|gate|capacity|pending|owner|item|out_index|output_transfer|wmask|error|start',rtl)):
                target('net',row['gate'])
    boundary=re.compile(r'/(lit_narrow|accumulator|jp_input_return|jp_shift_return|shifts|held_low|held_high|fifo_count|fifo_read)_reg_')
    registers=[];gates=[];macros=[]
    for path,cell in cells.items():
        if cell['ref'] in modules:continue
        pins=cell['pins']
        if path=='shared_memory/joined_rsp_valid_reg':
            for pin in ['D','Q','QN']:
                if pin in pins:target('pin',path+'/'+pin)
        if boundary.search(path) and '/accelerator/controller/core/' in path:
            registers.append(dict(cell=path,**cell))
            for pin in (['D','EN','Q','QN'] if '/jp_shift_return' in path else ['Q','QN']):
                if pin in pins:target('pin',path+'/'+pin)
        if '/dma_frontend/loading_dma/' in path and re.search(r'/(source_remaining|dest_remaining|pd_count)_reg_',path):
            registers.append(dict(cell=path,**cell))
            for pin in ['D','Q','QN','RDN','SDN']:
                if pin in pins:target('pin',path+'/'+pin)
        if cell['ref'].startswith('CLKLANA') and '/accelerator/controller/core/' in path:
            gates.append(dict(cell=path,**cell))
            for pin in ['CK','E','TE','Q']:
                if pin in pins:target('pin',path+'/'+pin)
        if cell['ref']=='RAMSP128X16' and '/shift_memory/' in path:
            for pin in ['CLK','CEN','GWEN']:
                target('pin',path+'/'+pin)
            for bit in range(16):target('pin',path+'/Q[%d]'%bit)
        if cell['ref']=='RAMSP128X16' and 'ap_input_rows_' in path:
            macros.append(dict(cell=path,**cell))
            for stem,count in [('D',16),('Q',16),('WEN',16),('A',7)]:
                for bit in range(count):target('pin',path+'/'+stem+'[%d]'%bit)
            for pin in ['CLK','CEN','GWEN']:target('pin',path+'/'+pin)
    shared_body=modules[hierarchy['shared_memory']]
    for stem in ['joined_rsp_valid','joined_rsp_ready']:
        for candidate in [stem,stem+'_BAR']:
            if re.search(r'\b'+candidate+r'\b',shared_body):target('net','shared_memory/'+candidate)
    out=REPORT/'activity-mapping'/('native-review-'+review_group(name))/name;out.mkdir(parents=True,exist_ok=True)
    dump(out/'inventory.json',dict(variant=name,tag=profile['tag'],hierarchy=hierarchy,cells=cells,mappings=mappings,registers=registers,gates=gates,input_macros=macros))
    dump(out/'saif-index.json',dict(duration=duration,activity=activity))
    dump(out/'query-targets.json',targets)
    summary=dict(variant=name,tag=profile['tag'],mapped_rules=len(mappings),cell_inverted_rules=sum(r['cell'] and r['inverted'] for r in mappings),
                 saif_signals=len(activity),duration=duration,actual_boundary_registers=len(registers),actual_core_gates=len(gates),input_macros=len(macros),query_targets=len(targets))
    dump(out/'inventory-summary.json',summary);print(json.dumps(summary),flush=True)
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('variants',nargs='+');args=parser.parse_args()
    for name in args.variants:inventory(name)
