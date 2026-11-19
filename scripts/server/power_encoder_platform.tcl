set corner ss
if {[info exists env(XPIAN_CORNER)]} {set corner $env(XPIAN_CORNER)}
set tag ${corner}_ema2
if {[info exists env(XPIAN_TAG)]} {set tag $env(XPIAN_TAG)}
set report reports/server/encoder_platform_sm40_$tag/power_$env(XPIAN_TASK)
file mkdir $report
if {$corner eq "ss"} {
    set cell_name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db
    set ram_corner ss_0p99v_0p99v_125c
} else {
    set cell_name scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db
    set ram_corner tt_1p10v_1p10v_25c
}
set platform_libraries [glob build/server/technology/platform_ram_db/*.db]
set cell_library [exec find build/server/technology -name $cell_name]
set link_path [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_${ram_corner}.db build/server/technology/ram_db/RAMSP128X16_${ram_corner}.db]
set link_path [concat $link_path $platform_libraries]
set_app_var power_enable_analysis true
set_app_var power_analysis_mode averaged
read_verilog build/server/encoder_platform_sm40_$tag/netlist.v
current_design kwt_encoder_platform
link_design
source constraints/public_encoder_platform.sdc
puts "XPIAN_ASSESSMENT_SDC=constraints/public_encoder_platform.sdc"
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
source build/server/encoder_platform_sm40_$tag/saif_map.tcl
set activity [format "reports/public_encoder/measured_activity_%02d.saif" $env(XPIAN_TASK)]
read_saif -strip_path server_encoder_tb/dut/platform $activity
update_power
redirect $report/power.rpt {report_power -verbose -hierarchy}
redirect $report/annotation.rpt {report_switching_activity}
redirect $report/unannotated.rpt {report_switching_activity -list_not_annotated}
puts "XPIAN_ENCODER_POWER_DONE task=$env(XPIAN_TASK)"
exit
