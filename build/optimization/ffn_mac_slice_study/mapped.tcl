set synopsys_auto_setup true
set_host_options -max_cores 4
set variant $env(MAC_SLICE_VARIANT)
set base build/optimization/ffn_mac_slice_study
set report reports/optimization/ffn_mac_slice_study/native/$variant/formal
file mkdir $report
set_svf $base/native/$variant/design.svf
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
read_db -technology_library $cell_library
read_sverilog -r [list $base/kwt_ffn_clock_gate.sv $base/kwt_ffn_requantize.sv $base/$variant/mac_slice.sv $base/top.sv]
set_top r:/WORK/mac_slice_top
read_verilog -i $base/native/$variant/netlist.v
set_top i:/WORK/mac_slice_top
match
set ok [verify]
redirect $report/failing.rpt {report_failing_points}
redirect $report/unmatched.rpt {report_unmatched_points}
puts "MAC_SLICE_MAPPED_EQUIVALENT=$ok"
exit [expr {!$ok}]
