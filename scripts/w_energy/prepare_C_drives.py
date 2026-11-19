"""Select fixed, report-observed driver replacements with identical factory functions."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[2]

def main():
    out=ROOT/'reports/optimization/ffn_w_energy/recovery/hold-drive-v1';out.mkdir(parents=True,exist_ok=True)
    prefix='soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller';core=prefix+'/core'
    targets=[(prefix+'/U117','NOR2XBV2','NOR2XBV8')]
    targets.extend((core+'/'+leaf,'CLKINV0','CLKINV12') for leaf in ['U3365','U1797'])
    targets.extend((core+'/'+leaf,'CLKBUFV2','CLKBUFV12') for leaf in ['U724','U705','U403','U3158','U1368','U1367'])
    for leaf,old,new in [('U238','CLKINV2','CLKINV8'),('U9049','XNOR2V3','XNOR2V8'),('U9050','BUFV4RQ','BUFV8RQ'),('U712','CLKBUFV2','CLKBUFV8'),('U3132','CLKBUFV2','CLKBUFV8'),('U7140','CLKINV0','CLKINV12'),('U3130','CLKBUFV2','CLKBUFV8'),('U173','XNOR2V3','XNOR2V8'),('U6499','BUFV4RQ','BUFV8RQ'),('U3360','NAND2CV0','NAND2CV4'),('U711','CLKBUFV2','CLKBUFV8'),('U707','CLKBUFV2','CLKBUFV8')]:targets.append((core+'/'+leaf,old,new))
    vendor=(ROOT/'build/server/technology/S40/smic/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/verilog/scc40nll_vhsc40_rvt.v').read_text()
    models=[];records=[]
    for cell,old,new in targets:
        old+='_12TR40';new+='_12TR40';functions=[]
        for ref in [old,new]:
            model=re.search(r'(?m)^\s*module\s+'+ref+r'\s*\([\s\S]*?\bendmodule',vendor).group();models.append(model)
            functions.append(re.findall(r'(?m)^\s*(not|buf|xor|xnor|nand|nor|and|or)\s+\w+\s*\(([^;]+)\);',model.split('specify')[0]))
        if not functions[0] or functions[0]!=functions[1]:raise RuntimeError('Inspect actual factory function '+cell)
        records.append(dict(cell=cell,old=old,new=new,literal_factory_function=functions[0],reason='actual reset recovery path weak fanout tree' if len(records)<9 else 'actual clk-group MAC input/broadcast path delay'))
    (out/'selected-drivers.json').write_text(json.dumps(dict(variant='ffn_wen_C',source_tag='opt_ffn_wen_C_hold_ss_ema2',targets=records,RTL_changed=False,source_reports=['hold-diagnostic-20261104','C-paths-20261104']),indent=2))
    (out/'literal-sized-cell-models.v').write_text('\n\n'.join(dict.fromkeys(models)))
    text='# C actual reset-recovery and MAC broadcast paths: same-function drive sizing only.\nset targets {\n'
    text+='\n'.join('    '+x['cell']+' '+x['old']+' '+x['new'] for x in records)+'\n}\n'
    text+='''set delta 0.0
foreach {path old new} $targets {
    set cell [get_cells $path]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual C hold driver $path"}
    set old_area [get_attribute [get_lib_cells */$old] area]
    set new_area [get_attribute [get_lib_cells */$new] area]
    set delta [expr {$delta+$new_area-$old_area}]
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_WEN_C_DRIVE $path $old -> $new"
}
puts "XPIAN_WEN_C_DRIVE_DONE cells=21 area_delta_um2=$delta"
'''
    (ROOT/'scripts/server/repair_ffn_w_energy_C_drive_v1.tcl').write_text(text)
    print('ACTUAL_REPORT_SELECTED_DRIVERS',len(records),'literal functions same')

if __name__=='__main__':main()
