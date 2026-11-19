set corner ss
if {[info exists env(XPIAN_CORNER)]} {set corner $env(XPIAN_CORNER)}
set tag ${corner}_ema2
if {[info exists env(XPIAN_TAG)]} {set tag $env(XPIAN_TAG)}
set report reports/server/encoder_sm40_$tag/pt
file mkdir $report
if {$corner eq "ss"} {
    set cell_name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db
    set ram_corner ss_0p99v_0p99v_125c
} else {
    set cell_name scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db
    set ram_corner tt_1p10v_1p10v_25c
}
set cell_library [exec find build/server/technology -name $cell_name]
set link_path [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_${ram_corner}.db build/server/technology/ram_db/RAMSP128X16_${ram_corner}.db]
read_verilog build/server/encoder_sm40_$tag/netlist.v
current_design kwt_encoder_accelerator
link_design
source constraints/accelerator.sdc
puts "XPIAN_ASSESSMENT_SDC=constraints/accelerator.sdc"
update_timing
redirect $report/units.rpt {report_units}
redirect $report/design.rpt {report_design}
redirect $report/check_timing.rpt {check_timing -verbose}
redirect $report/coverage.rpt {report_analysis_coverage}
redirect $report/timing_max.rpt {report_timing -delay_type max -max_paths 10 -slack_lesser_than 1000000 -significant_digits 6 -path_type full_clock_expanded -input_pins -nets -transition_time -capacitance}
redirect $report/timing_min.rpt {report_timing -delay_type min -max_paths 10 -slack_lesser_than 1000000 -significant_digits 6}
redirect $report/constraints.rpt {report_constraint -all_violators -significant_digits 6}
set path [get_timing_paths -delay_type max -max_paths 1 -slack_lesser_than 1000000]
puts "XPIAN_SM40_MAX_SLACK_NS=[get_attribute $path slack]"
puts "XPIAN_SM40_START=[get_object_name [get_attribute $path startpoint]]"
puts "XPIAN_SM40_END=[get_object_name [get_attribute $path endpoint]]"
if {[info exists env(XPIAN_INTERNAL_MAX_DELAY_NS)]} {
    read_sdc build/server/encoder_sm40_$tag/design.sdc
    update_timing
    redirect $report/implementation_timing.rpt {report_timing -delay_type max -max_paths 10 -slack_lesser_than 1000000 -significant_digits 6}
    redirect $report/implementation_constraints.rpt {report_constraint -all_violators -significant_digits 6}
    puts "XPIAN_IMPLEMENTATION_MAX_DELAY_NS=$env(XPIAN_INTERNAL_MAX_DELAY_NS)"
}
puts "XPIAN_SM40_PT_DONE corner=$corner"
exit
