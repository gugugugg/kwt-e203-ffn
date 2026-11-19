"""Group aliases by this final's literal wires and hierarchy port connections."""
from pathlib import Path
from collections import defaultdict
import argparse,json,re
from ffn_sr_area import ROOT,REPORT,dump,review_group

def analyze(name):
    out=REPORT/'activity-mapping'/('native-review-'+review_group(name))/name
    data=json.loads((out/'inventory.json').read_text());hier=data['hierarchy'];cells=data['cells'];mappings=data['mappings']
    activity=json.loads((out/'saif-index.json').read_text())['activity']
    netlist=(ROOT/'build/server'/('complete_soc_sm40_'+data['tag'])/'netlist.v').read_text()
    modules={m.group(1):m.group(2) for m in re.finditer(r'module\s+(\w+)\s*\(([\s\S]*?)endmodule',netlist)}
    widths={}
    for mod,body in modules.items():
        d={}
        for m in re.finditer(r'(?m)^\s*(input|output|wire)\s+(?:\[(\d+):(\d+)\]\s*)?([^;]+);',body):
            for n in m.group(4).split(','):
                d[n.strip()]=(int(m.group(2)),int(m.group(3))) if m.group(2) else None
        widths[mod]=d
    parent={}
    def find(n):
        n=n.lstrip('/')
        if n not in parent:parent[n]=n
        if parent[n]!=n:parent[n]=find(parent[n])
        return parent[n]
    def union(a,b):
        if "'" in a or "'" in b:return
        a=find(a);b=find(b)
        if a!=b:parent[b]=a
    def expand(expr,mod,path):
        expr=re.sub(r'\s','',expr)
        if expr.startswith('{'):
            return sum((expand(x,mod,path) for x in expr[1:-1].split(',')),[])
        if "'" in expr:return [expr]
        m=re.fullmatch(r'(\w+)\[(\d+):(\d+)\]',expr)
        if m:
            hi,lo=int(m.group(2)),int(m.group(3));step=1 if lo>hi else -1
            return [(path+'/'+m.group(1)+'[%d]'%bit).lstrip('/') for bit in range(hi,lo+step,step)]
        if expr in widths[mod] and widths[mod][expr]:
            hi,lo=widths[mod][expr];step=1 if lo>hi else -1
            return [(path+'/'+expr+'[%d]'%bit).lstrip('/') for bit in range(hi,lo+step,step)]
        return [(path+'/'+expr).lstrip('/')]
    for path,mod in hier.items():
        for left,right in re.findall(r'\bassign\s+([^;=]+)=([^;]+);',modules[mod]):
            a=expand(left,mod,path);b=expand(right,mod,path)
            if len(a)==len(b):
                for x,y in zip(a,b):union(x,y)
        if not path:continue
        upper=path.rsplit('/',1)[0] if '/' in path else '';upmod=hier[upper]
        for pin,expr in cells[path]['pins'].items():
            a=expand(pin,mod,path);b=expand(expr,upmod,upper)
            if len(a)==len(b):
                for x,y in zip(a,b):union(x,y)
    by=defaultdict(list)
    for row in mappings:
        if not row['cell']:by[find(row['gate'])].append(row)
    collisions=[]
    for g,items in by.items():
        vals=[dict(x,saif=activity[x['rtl']]) for x in items if x['rtl'] in activity]
        if len({tuple(sorted(x['saif'].items())) for x in vals})>1:collisions.append(dict(segment=g,aliases=vals))
    pins={};drivers=defaultdict(list)
    vendor=(out/'vendor-functions.v').read_text()
    vmods={m.group(1):m.group(2) for m in re.finditer(r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule',vendor)}
    outputs={ref:set(re.findall(r'\boutput\s+(\w+)\s*;',body)) for ref,body in vmods.items()}
    for path,cell in cells.items():
        if cell['ref'] in modules:continue
        upper=path.rsplit('/',1)[0] if '/' in path else ''
        for pin,expr in cell['pins'].items():
            values=expand(expr,cell['parent_module'],upper)
            if len(values)==1:
                pins[path+'/'+pin]=values[0]
                if pin in outputs.get(cell['ref'],set()):drivers[find(values[0])].append(dict(cell=path,ref=cell['ref'],pin=pin,net=values[0]))
    cell_rules=[]
    for row in mappings:
        if row['cell'] and row['inverted']:
            c=cells[row['gate']];entry=dict(row,ref=c['ref'],pins=c['pins'],saif=activity.get(row['rtl']))
            for pin in ['D','Q','QN','RDN','SDN']:
                n=pins.get(row['gate']+'/'+pin)
                if n:
                    entry[pin+'_net']=n
                    entry[pin+'_drivers']=drivers.get(find(n),[])
                    entry[pin+'_aliases']=by.get(find(n),[])
            cell_rules.append(entry)
    for row in collisions:row['drivers']=drivers.get(row['segment'],[])
    dump(out/'net-alias-collisions.json',collisions)
    dump(out/'cell-inverted-review-inputs.json',cell_rules)
    dump(out/'connectivity.json',dict(representatives={n:find(n) for n in list(parent)},pins=pins,drivers=drivers,aliases=by))
    print(name,'wire_segments',len(by),'mixed_activity_segments',len(collisions),'inverted_cell_rules',len(cell_rules),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('variants',nargs='+')
    for name in p.parse_args().variants:analyze(name)
