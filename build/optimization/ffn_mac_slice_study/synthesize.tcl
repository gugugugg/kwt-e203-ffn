set_host_options -max_cores 4
set variant $env(MAC_SLICE_VARIANT)
set base build/optimization/ffn_mac_slice_study
set out $base/native/$variant
set report reports/optimization/ffn_mac_slice_study/native/$variant
file mkdir $out $report
define_design_lib WORK -path $out/work
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set_app_var target_library [list $cell_library]
set_app_var synthetic_library dw_foundation.sldb
set_app_var link_library [concat [list *] $target_library dw_foundation.sldb]
set_svf $out/design.svf
saif_map -start
analyze -format sverilog [list $base/kwt_ffn_clock_gate.sv $base/kwt_ffn_requantize.sv $base/$variant/mac_slice.sv $base/top.sv]
elaborate mac_slice_top
current_design mac_slice_top
link
uniquify
source $base/slice.sdc
set_fix_hold [get_clocks clk]
redirect $report/check_design.rpt {check_design}
compile_ultra -no_autoungroup
change_names -rules verilog -hierarchy
redirect $report/area.rpt {report_area -hierarchy}
redirect $report/timing.rpt {report_timing -max_paths 20 -significant_digits 9 -nets -transition_time -capacitance}
redirect $report/constraints.rpt {report_constraint -all_violators -significant_digits 9}
redirect $report/resources.rpt {report_resources -hierarchy}
redirect $report/cells.rpt {report_cell [get_cells -hierarchical *]}
redirect $report/design.rpt {report_design}
write -format ddc -hierarchy -output $out/design.ddc
write -format verilog -hierarchy -output $out/netlist.v
write_sdc $out/design.sdc
write_sdf $out/design.sdf
set_svf -off
puts "MAC_SLICE_SYNTH_DONE=$variant"
exit
