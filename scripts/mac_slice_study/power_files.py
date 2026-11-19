"""Prepare direct mapped-netlist activity measurement if timing screening passes."""
from prepare import OUT,REPORT

POWER='''set_host_options -max_cores 8
set variant $env(MAC_SLICE_VARIANT)
set task $env(MAC_SLICE_CASE)
set base build/optimization/ffn_mac_slice_study
set report reports/optimization/ffn_mac_slice_study/native/$variant/power_$task
file mkdir $report
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set link_path [list * $cell_library]
set_app_var power_enable_analysis true
set_app_var power_analysis_mode averaged
read_verilog $base/native/$variant/netlist.v
current_design mac_slice_top
link_design
source $base/slice.sdc
update_timing
set activity $base/native/$variant/activity_$task.saif
if {![read_saif -strip_path slice_replay_tb/dut $activity]} {error "Mapped slice SAIF annotation failed"}
update_power
redirect $report/power.rpt {report_power -verbose -hierarchy -significant_digits 9}
redirect $report/annotation.rpt {report_switching_activity}
redirect $report/unannotated.rpt {report_switching_activity -list_not_annotated}
redirect $report/design.rpt {report_design}
redirect $report/units.rpt {report_units}
set f [open $report/precise.json w]
puts $f "\\{"
puts $f "\\"internal_w\\":[get_attribute [current_design] internal_power],"
puts $f "\\"switching_w\\":[get_attribute [current_design] switching_power],"
puts $f "\\"leakage_w\\":[get_attribute [current_design] leakage_power],"
puts $f "\\"total_w\\":[get_attribute [current_design] total_power]"
puts $f "\\}"
close $f
set f [open $report/leaf-power.tsv w]
puts $f "cell\\tref\\tarea\\tinternal_w\\tswitching_w\\tleakage_w"
foreach_in_collection cell [get_cells -hierarchical -filter "is_hierarchical == false"] {
 puts $f "[get_object_name $cell]\\t[get_attribute $cell ref_name]\\t[get_attribute $cell area]\\t[get_attribute $cell internal_power]\\t[get_attribute $cell switching_power]\\t[get_attribute $cell leakage_power]"
}
close $f
puts "MAC_SLICE_DIRECT_GATE_SAIF=1"
puts "MAC_SLICE_POWER_DONE variant=$variant case=$task"
exit
'''

if __name__=='__main__':
    (OUT/'power.tcl').write_text(POWER)
    (REPORT/'source/power.tcl').write_text(POWER)
