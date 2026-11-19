"""Size only weak drivers present in this candidate's actual reset/data paths."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[2]
def main():
    base=ROOT/'reports/optimization/ffn_c_energy/received/hold-drive-v1/native-evidence';out=ROOT/'reports/optimization/ffn_c_energy/recovery/hold-drive-v2';out.mkdir(parents=True,exist_ok=True)
    vendor=next((ROOT/'reports/optimization/ffn_c_energy/received/initial-hold-paths/native-evidence').rglob('scc40nll_vhsc40_rvt.v')).read_text();targets={};pattern=r'^\s*(soc/\S+)/(Z|ZN)\s+\((\w+)\)\s*\n\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)'
    for label in ['data']:
        path=next(base.rglob('timing_max.rpt'));text=path.read_text()
        mapping={'NOR2XBV2':'NOR2XBV8','CLKINV0':'CLKINV12','CLKBUFV2':'CLKBUFV12'} if label=='reset' else {'CLKINV0':'CLKINV12','CLKINV2':'CLKINV8','CLKBUFV2':'CLKBUFV8','BUFV4RQ':'BUFV8RQ','BUFV2RQ':'BUFV8RQ','XNOR2V3':'XNOR2V8','NAND2CV0':'NAND2CV4'}
        for m in re.finditer(pattern,text,re.M):
            cell,ref=m[1],m[3];stem=ref.replace('_12TR40','');transition,delay=float(m[4]),float(m[5])
            if '/accelerator/controller/' not in cell or stem not in mapping or (transition<=.18 and delay<=.18):continue
            targets[cell]=dict(cell=cell,old=ref,new=mapping[stem]+'_12TR40',source_report=path.relative_to(ROOT).as_posix(),reported_transition_ns=transition,reported_cell_delay_ns=delay,reason='actual '+label+' path weak driver; same factory Boolean function')
    models=[]
    for row in targets.values():
        functions=[]
        for ref in [row['old'],row['new']]:
            model=re.search(r'(?m)^\s*module\s+'+ref+r'\s*\([\s\S]*?\bendmodule',vendor).group();models.append(model);functions.append(re.findall(r'(?m)^\s*(not|buf|xor|xnor|nand|nor|and|or)\s+\w+\s*\(([^;]+)\);',model.split('specify')[0]))
        if not functions[0] or functions[0]!=functions[1]:raise RuntimeError('Read actual factory function '+row['cell'])
        row['literal_factory_function']=functions[0]
    records=list(targets.values());(out/'selected-drivers.json').write_text(json.dumps(dict(variant='ffn_cen_SL',source_tag='opt_ffn_cen_SL_drive_v1_hold_ss_ema2',targets=records,RTL_changed=False),indent=2));(out/'literal-sized-cell-models.v').write_text('\n\n'.join(dict.fromkeys(models)))
    text='# Own C-energy actual report-selected same-function drive sizing.\nset targets {\n'+'\n'.join('    '+row['cell']+' '+row['old']+' '+row['new'] for row in records)+'\n}\n'
    text+='''set delta 0.0
foreach {path old new} $targets {
    set cell [get_cells $path]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual C-energy hold driver $path"}
    set old_area [get_attribute [get_lib_cells */$old] area]
    set new_area [get_attribute [get_lib_cells */$new] area]
    set delta [expr {$delta+$new_area-$old_area}]
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_CEN_SL_DRIVE $path $old -> $new"
}
puts "XPIAN_CEN_SL_DRIVE_DONE area_delta_um2=$delta"
'''
    (ROOT/'scripts/server/repair_ffn_c_energy_SL_drive_v2.tcl').write_text(text);print('OWN_REPORT_DRIVERS_SAME_FACTORY_FUNCTION',len(records),flush=True)
if __name__=='__main__':main()
