set_host_options -max_cores 8
set variant $env(MAC_SLICE_VARIANT)
set base build/optimization/ffn_mac_slice_study
set report reports/optimization/ffn_mac_slice_study/native/$variant/pt
file mkdir $report
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set link_path [list * $cell_library]
read_verilog $base/native/$variant/netlist.v
current_design mac_slice_top
link_design
source $base/slice.sdc
update_timing
redirect $report/units.rpt {report_units}
redirect $report/design.rpt {report_design}
redirect $report/clocks.rpt {report_clock}
redirect $report/check_timing.rpt {check_timing -verbose}
redirect $report/coverage.rpt {report_analysis_coverage}
redirect $report/timing_max.rpt {report_timing -delay_type max -max_paths 20 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets -transition_time -capacitance}
redirect $report/timing_min.rpt {report_timing -delay_type min -max_paths 20 -slack_lesser_than 1000000 -significant_digits 9}
redirect $report/constraints.rpt {report_constraint -all_violators -significant_digits 9}
redirect $report/clock_gating_setup.rpt {report_constraint -clock_gating_setup -verbose -significant_digits 9}
redirect $report/clock_gating_hold.rpt {report_constraint -clock_gating_hold -verbose -significant_digits 9}
set setup [get_attribute [get_timing_paths -delay_type max -max_paths 1 -slack_lesser_than 1000000] slack]
set hold [get_attribute [get_timing_paths -delay_type min -max_paths 1 -slack_lesser_than 1000000] slack]
puts "MAC_SLICE_SETUP_NS=$setup"
puts "MAC_SLICE_HOLD_NS=$hold"
puts "MAC_SLICE_PT_DONE=$variant"
exit
