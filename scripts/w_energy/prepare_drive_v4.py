"""Select fixed, report-observed driver replacements with identical factory functions."""
from pathlib import Path
import json,re,sys
ROOT=Path(__file__).resolve().parents[2]

def main():
    out=ROOT/'reports/optimization/ffn_w_energy/recovery/hold-drive-v4';out.mkdir(parents=True,exist_ok=True)
    prefix='soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller';core=prefix+'/core'
    kind=sys.argv[1];targets=[]
    by_kind={'SL':[('U5949','XNOR2V3','XNOR2V8'),('U2576','BUFV2RQ','BUFV8RQ')]}
    out=ROOT/'reports/optimization/ffn_w_energy/recovery'/('hold-drive-'+kind+'-v4');out.mkdir(parents=True,exist_ok=True)
    for leaf,old,new in by_kind[kind]:targets.append((core+'/'+leaf,old,new))
    vendor=(ROOT/'build/server/technology/S40/smic/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/verilog/scc40nll_vhsc40_rvt.v').read_text()
    models=[];records=[]
    for cell,old,new in targets:
        old+='_12TR40';new+='_12TR40';functions=[]
        for ref in [old,new]:
            model=re.search(r'(?m)^\s*module\s+'+ref+r'\s*\([\s\S]*?\bendmodule',vendor).group();models.append(model)
            functions.append(re.findall(r'(?m)^\s*(not|buf|xor|xnor|nand|nor|and|or)\s+\w+\s*\(([^;]+)\);',model.split('specify')[0]))
        if not functions[0] or functions[0]!=functions[1]:raise RuntimeError('Inspect actual factory function '+cell)
        records.append(dict(cell=cell,old=old,new=new,literal_factory_function=functions[0],reason='remaining actual clk-group MAC broadcast paths after v3 sizing'))
    (out/'selected-drivers.json').write_text(json.dumps(dict(variant='ffn_wen_'+kind,source_tag='opt_ffn_wen_'+kind+'_drive_v3_hold_ss_ema2',targets=records,RTL_changed=False,source_reports=['drive-results-v3']),indent=2))
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
    text=text.replace('cells=21','cells='+str(len(records))).replace('WEN_C_DRIVE','WEN_'+kind+'_DRIVE')
    (ROOT/('scripts/server/repair_ffn_w_energy_'+kind+'_drive_v4.tcl')).write_text(text)
    print('ACTUAL_REPORT_SELECTED_DRIVERS',len(records),'literal functions same')

if __name__=='__main__':main()
