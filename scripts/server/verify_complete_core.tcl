set synopsys_auto_setup true
set report reports/complete_soc/formality_core
file mkdir $report
set_host_options -max_cores 8
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
read_db -technology_library $cell_library
foreach memory {RAMSP1024X16 RAMSP128X16} {
    read_db -technology_library build/server/technology/ram_db/${memory}_ss_0p99v_0p99v_125c.db
}
foreach library [glob build/server/technology/platform_ram_db/*.db] {read_db -technology_library $library}
read_verilog -r build/server/unified_platform_sm40_dual_v3_ss_ema2/netlist.v
set_top r:/WORK/kwt_encoder_accelerator
read_verilog -i build/server/complete_soc_sm40_complete_v3_ss_ema2/netlist.v
set_top i:/WORK/kwt_encoder_accelerator
match
set verified [verify]
redirect $report/failing.rpt {report_failing_points}
redirect $report/unmatched.rpt {report_unmatched_points}
puts "XPIAN_COMPLETE_CORE_EQUIVALENT=$verified"
exit [expr {!$verified}]
