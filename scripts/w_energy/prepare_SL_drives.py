"""Select fixed, report-observed SL driver replacements with identical factory functions."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[2]

def main():
    out=ROOT/'reports/optimization/ffn_w_energy/recovery/hold-drive-SL-v1';out.mkdir(parents=True,exist_ok=True)
    prefix='soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller';core=prefix+'/core'
    targets=[]
    for leaf,old,new in [('U872','XNOR2V3','XNOR2V8'),('U5997','BUFV4RQ','BUFV8RQ'),('U629','NAND2CV1','NAND2CV4'),('U513','BUFV2RQ','BUFV8RQ'),('U2787','CLKINV4','CLKINV12'),('U2802','NAND2V2','NAND2V12'),('U2801','CLKINV2','CLKINV12'),('U167','CLKINV2','CLKINV8'),('U168','XNOR2V3','XNOR2V8'),('U675','CLKBUFV6','CLKBUFV12'),('U2878','BUFV4RQ','BUFV8RQ'),('U516','BUFV2RQ','BUFV8RQ'),('U2029','XNOR2V3','XNOR2V8'),('U7878','BUFV4RQ','BUFV8RQ'),('U2019','NAND2CV2','NAND2CV4'),('U533','CLKBUFV2','CLKBUFV8')]:targets.append((core+'/'+leaf,old,new))
    vendor=(ROOT/'build/server/technology/S40/smic/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/verilog/scc40nll_vhsc40_rvt.v').read_text()
    models=[];records=[]
    for cell,old,new in targets:
        old+='_12TR40';new+='_12TR40';functions=[]
        for ref in [old,new]:
            model=re.search(r'(?m)^\s*module\s+'+ref+r'\s*\([\s\S]*?\bendmodule',vendor).group();models.append(model)
            functions.append(re.findall(r'(?m)^\s*(not|buf|xor|xnor|nand|nor|and|or)\s+\w+\s*\(([^;]+)\);',model.split('specify')[0]))
        if not functions[0] or functions[0]!=functions[1]:raise RuntimeError('Inspect actual factory function '+cell)
        records.append(dict(cell=cell,old=old,new=new,literal_factory_function=functions[0],reason='actual clk-group MAC input/broadcast path delay'))
    (out/'selected-drivers.json').write_text(json.dumps(dict(variant='ffn_wen_SL',source_tag='opt_ffn_wen_SL_hold_ss_ema2',targets=records,RTL_changed=False,source_reports=['SL-paths-20261104','SL-paths-20261104']),indent=2))
    (out/'literal-sized-cell-models.v').write_text('\n\n'.join(dict.fromkeys(models)))
    text='# SL actual MAC broadcast paths: same-function drive sizing only.\nset targets {\n'
    text+='\n'.join('    '+x['cell']+' '+x['old']+' '+x['new'] for x in records)+'\n}\n'
    text+='''set delta 0.0
foreach {path old new} $targets {
    set cell [get_cells $path]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual SL hold driver $path"}
    set old_area [get_attribute [get_lib_cells */$old] area]
    set new_area [get_attribute [get_lib_cells */$new] area]
    set delta [expr {$delta+$new_area-$old_area}]
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_WEN_SL_DRIVE $path $old -> $new"
}
puts "XPIAN_WEN_SL_DRIVE_DONE cells=16 area_delta_um2=$delta"
'''
    (ROOT/'scripts/server/repair_ffn_w_energy_SL_drive_v1.tcl').write_text(text)
    print('ACTUAL_REPORT_SELECTED_DRIVERS',len(records),'literal functions same')

if __name__=='__main__':main()
