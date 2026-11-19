"""Select only drivers on W's own 122 measured failing broadcast paths."""
import json
import re
from pathlib import Path
from prepare import ROOT,REPORT


def main():
    diagnosis=REPORT/'received/broadcast-v1-result/native-evidence'
    query=REPORT/'received/broadcast-v1-all-paths/native-evidence/reports/optimization/ffn_c16_efficiency/recovery/broadcast-resize-v1/path-diagnostic'
    paths=(query/'all_failed_setup.rpt').read_text()
    netlist=(diagnosis/'build/server/complete_soc_sm40_opt_ffn_ce_W_broadcast_v1_hold_ss_ema2/netlist.v').read_text()
    modules=re.findall(r'module\s+(\w+)\s*\(([\s\S]*?)endmodule',netlist)
    body=next(text for name,text in modules if 'jp_input_return_reg_3_' in text and 'accumulator_reg_0__35_' in text)
    targets=[('U2799','CLKINV4','CLKINV8'),('U2815','NAND2V2','NAND2V8'),('U2814','CLKINV2','CLKINV4'),
        ('U112','XNOR2V3','XNOR2V6'),('U6637','BUFV2RQ','BUFV8RQ'),
        ('U2933','XNOR2V3','XNOR2V6'),('U772','CLKBUFV6','CLKBUFV12'),
        ('U5962','XNOR2V3','XNOR2V6'),('U2585','BUFV2RQ','BUFV8RQ'),
        ('U6048','XNOR2V3','XNOR2V6'),('U775','BUFV4RQ','BUFV8RQ'),
        ('U2545','XNOR2V3','XNOR2V6'),('U2580','BUFV2RQ','BUFV8RQ')]
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
    out=REPORT/'recovery/broadcast-resize-v2';out.mkdir(parents=True,exist_ok=True)
    (out/'selected-drivers.json').write_text(json.dumps(dict(targets=records,failed_paths=122,
        measured_setup_ns=-0.259464,measured_hold_ns=0.144989,RTL_changed=False,
        rationale='Only observed high-fanout inverter/XNOR/buffer chains from seven input-return bits; no new state or pipeline'),indent=2))
    lines=['# W own 122 failing setup paths: same-function broadcast drive resizing.',
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
        'puts "XPIAN_W_BROADCAST_REPAIR_DONE cells=13 area_delta_um2=$delta"']
    (ROOT/'scripts/server/repair_ffn_c16_efficiency_broadcast_v2.tcl').write_text('\n'.join(lines)+'\n')
    print('EFFICIENCY_ACTUAL_DRIVER_REPAIR_PREPARED',len(records),flush=True)


if __name__=='__main__':main()
