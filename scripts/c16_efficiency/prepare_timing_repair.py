"""Select only drivers on W's own 67 measured failing broadcast paths."""
import json
import re
from pathlib import Path
from prepare import ROOT,REPORT


def main():
    diagnosis=REPORT/'received/hold-timing-diagnosis/native-evidence'
    query=REPORT/'received/broadcast-diagnostic/native-evidence/reports/optimization/ffn_c16_efficiency/recovery/hold-timing-20261104/broadcast-diagnostic'
    paths=(query/'all_failed_setup.rpt').read_text()
    netlist=(diagnosis/'build/server/complete_soc_sm40_opt_ffn_ce_W_hold_ss_ema2/netlist.v').read_text()
    modules=re.findall(r'module\s+(\w+)\s*\(([\s\S]*?)endmodule',netlist)
    body=next(text for name,text in modules if 'jp_input_return_reg_3_' in text and 'accumulator_reg_0__35_' in text)
    targets=[('U105','INV2SR','INV4SR'),('U5356','XNOR2V3','XNOR2V6'),('U5357','BUFV4RQ','BUFV8RQ'),
        ('U176','CLKINV2','CLKINV4'),('U177','XNOR2V3','XNOR2V6'),('U679','CLKBUFV6','CLKBUFV12'),('U2890','BUFV4RQ','BUFV8RQ'),
        ('U2914','CLKINV0','CLKINV4'),('U730','BUFV2RQ','BUFV8RQ'),
        ('U96','INV2SR','INV4SR'),('U95','XNOR2V3','XNOR2V6'),('U6010','BUFV4RQ','BUFV8RQ'),
        ('U182','XNOR2V3','XNOR2V6'),('U7856','BUFV2RQ','BUFV8RQ'),('U7891','XNOR2V3','XNOR2V6')]
    library=(query/'driver_library.rpt').read_text()
    records=[]
    for cell,old,new in targets:
        old+='_12TR40';new+='_12TR40'
        if not re.search(r'\b'+old+r'\s+'+cell+r'\s*\(',body):raise RuntimeError('Own actual driver differs: '+cell)
        touched=[block for block in paths.split('  Startpoint: ')[1:] if '/core/'+cell+'/' in block]
        if not touched:raise RuntimeError('Driver is absent from measured failing paths: '+cell)
        for ref in [old,new]:
            if not re.search(r'/'+ref+r' AREA ',library):raise RuntimeError('Same SS library driver not found: '+ref)
        records.append(dict(cell=cell,old=old,new=new,measured_failed_paths=len(touched),
            original_slack_ns=min(float(re.findall(r'slack\s+\(\w+\)\s+(-?[\d.]+)',p)[0]) for p in touched)))
    out=REPORT/'recovery/broadcast-resize-v1';out.mkdir(parents=True,exist_ok=True)
    (out/'selected-drivers.json').write_text(json.dumps(dict(targets=records,failed_paths=67,
        measured_setup_ns=-0.337498,measured_hold_ns=0.144989,RTL_changed=False,
        rationale='Only observed high-fanout inverter/XNOR/buffer chains from six input-return bits; no new state or pipeline'),indent=2))
    lines=['# W own 67 failing setup paths: same-function broadcast drive resizing.',
        'set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core','set targets {']
    lines+=['    %(cell)s %(old)s %(new)s'%r for r in records]
    lines+=['}','set delta 0.0','foreach {leaf old new} $targets {',
        '    set cell [get_cells $prefix/$leaf]',
        '    if {[get_attribute $cell ref_name] ne $old} {error "Read own W broadcast driver $prefix/$leaf"}',
        '    set old_area [get_attribute [get_lib_cells */$old] area]',
        '    set new_area [get_attribute [get_lib_cells */$new] area]',
        '    set delta [expr {$delta+$new_area-$old_area}]',
        '    puts "XPIAN_W_BROADCAST_SIZE $prefix/$leaf $old -> $new area_delta=[expr {$new_area-$old_area}]"',
        '    size_cell $cell [get_lib_cells */$new]','}',
        'puts "XPIAN_W_BROADCAST_REPAIR_DONE cells=15 area_delta_um2=$delta"']
    (ROOT/'scripts/server/repair_ffn_c16_efficiency_broadcast.tcl').write_text('\n'.join(lines)+'\n')
    print('EFFICIENCY_ACTUAL_DRIVER_REPAIR_PREPARED',len(records),flush=True)


if __name__=='__main__':main()
