"""Select same-function sizes only for weak cells on this candidate's violated paths."""
from pathlib import Path
import argparse,json,re
ROOT=Path(__file__).resolve().parents[2];REPORT=ROOT/'reports/optimization/ffn_c_area'

def main():
    p=argparse.ArgumentParser();p.add_argument('variant');p.add_argument('--evidence',required=True);p.add_argument('--vendor');p.add_argument('--revision',type=int,default=1);p.add_argument('--source-tag',required=True);a=p.parse_args()
    base=ROOT/a.evidence;vendor=(ROOT/a.vendor if a.vendor else next(base.rglob('scc40nll_vhsc40_rvt.v'))).read_text();targets={}
    mapping={'CLKINV0':'CLKINV12','CLKINV2':'CLKINV8','CLKINV3':'CLKINV12','CLKINV4':'CLKINV12','CLKBUFV2':'CLKBUFV8','CLKBUFV6':'CLKBUFV12','BUFV2RQ':'BUFV8RQ','BUFV4RQ':'BUFV8RQ','XNOR2V3':'XNOR2V8','NAND2CV0':'NAND2CV4','NAND2CV1':'NAND2CV4','NAND2V2':'NAND2V8','INV2SR':'INV8SR'}
    pattern=r'^\s*(soc/\S+)/(Z|ZN)\s+\((\w+)\)\s*\n\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)'
    paths=list(base.rglob('data.rpt')) or list(base.rglob('timing_max.rpt'))
    for path in paths:
        for block in re.split(r'(?=  Startpoint:)',path.read_text()):
            slack=re.search(r'slack\s+\(VIOLATED\)\s+(-?[\d.]+)',block)
            if not slack:continue
            for m in re.finditer(pattern,block,re.M):
                cell,ref=m[1],m[3];stem=ref.replace('_12TR40','');transition,delay=float(m[4]),float(m[5])
                if '/accelerator/controller/' not in cell or stem not in mapping or max(transition,delay)<=.18:continue
                targets[cell]=dict(cell=cell,old=ref,new=mapping[stem]+'_12TR40',source_report=path.relative_to(ROOT).as_posix(),reported_transition_ns=transition,reported_cell_delay_ns=delay,violated_slack_ns=float(slack[1]),reason='Own violated data path: weak buffer/inverter or high-fanout shared multiplier control, same factory function')
    models=[]
    for row in targets.values():
        functions=[]
        for ref in [row['old'],row['new']]:
            m=re.search(r'(?m)^\s*module\s+'+ref+r'\s*\([\s\S]*?\bendmodule',vendor)
            if not m:raise RuntimeError('Read actual same-library cell '+ref)
            model=m.group();models.append(model);functions.append(re.findall(r'(?m)^\s*(not|buf|xor|xnor|nand|nor|and|or)\s+\w+\s*\(([^;]+)\);',model.split('specify')[0]))
        if not functions[0] or functions[0]!=functions[1]:raise RuntimeError('Read actual same-function model '+row['cell'])
        row['literal_factory_function']=functions[0]
    out=REPORT/'recovery'/(a.variant+'-drive-v%d'%a.revision);out.mkdir(parents=True,exist_ok=True)
    script='scripts/server/repair_ffn_c_area_'+a.variant.rsplit('_',1)[1]+'_drive_v%d.tcl'%a.revision
    new='opt_'+a.variant+'_drive_v%d_hold_ss_ema2'%a.revision
    cfg=dict(variant=a.variant,source_tag=a.source_tag,new_tag=new,revision=a.revision,repair_script=script,targets=list(targets.values()),RTL_changed=False,parameter_scan=False)
    (out/'selected-drivers.json').write_text(json.dumps(cfg,indent=2));(out/'literal-sized-cell-models.v').write_text('\n\n'.join(dict.fromkeys(models)))
    text='# Actual violated path cells only; same literal factory function.\nset targets {\n'+'\n'.join('    '+r['cell']+' '+r['old']+' '+r['new'] for r in targets.values())+'\n}\n'
    text+='''set delta 0.0
foreach {path old new} $targets {
    set cell [get_cells $path]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual own checkpoint driver $path"}
    set delta [expr {$delta+[get_attribute [get_lib_cells */$new] area]-[get_attribute [get_lib_cells */$old] area]}]
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_C_AREA_SAME_FUNCTION_DRIVE $path $old -> $new"
}
puts "XPIAN_C_AREA_SAME_FUNCTION_DRIVE_DONE area_delta_um2=$delta"
'''
    (ROOT/script).write_text(text);print('C_AREA_OWN_REPORT_DRIVES',a.variant,len(targets),new,flush=True)

if __name__=='__main__':main()
