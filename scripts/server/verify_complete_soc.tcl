set synopsys_auto_setup true
set tag complete_v5_ss_ema2
set report reports/server/complete_soc_sm40_$tag/formality_rtl
file mkdir $report
set_host_options -max_cores 8
set_svf [list build/server/complete_soc_sm40_complete_v2_ss_ema2/design.svf build/server/complete_soc_sm40_complete_v3_ss_ema2/design.svf build/server/complete_soc_sm40_complete_v4_ss_ema2/design.svf build/server/complete_soc_sm40_$tag/design.svf]
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
read_db -technology_library $cell_library
foreach memory {RAMSP1024X16 RAMSP128X16} {
    read_db -technology_library build/server/technology/ram_db/${memory}_ss_0p99v_0p99v_125c.db
}
foreach library [glob build/server/technology/platform_ram_db/*.db] {read_db -technology_library $library}
set upstream [file normalize build/server/official_2025/e203_hbirdv2-master/rtl/e203]
set_app_var search_path [concat [list [pwd] [file normalize rtl/encoder] [file normalize rtl/public_encoder] [file normalize build/complete_soc] $upstream/core $upstream/perips $upstream/perips/apb_i2c] $search_path]
set stream [open build/complete_soc/synthesis_files.f r]
set sources {}
foreach source [split [string trim [read $stream]] "\n"] {lappend sources [file normalize $source]}
close $stream
read_sverilog -r $sources
set_top r:/WORK/kwt_complete_soc
read_verilog -i [file normalize build/server/complete_soc_sm40_$tag/netlist.v]
set_top i:/WORK/kwt_complete_soc
match
set verified [verify]
redirect $report/failing.rpt {report_failing_points}
redirect $report/unmatched.rpt {report_unmatched_points}
puts "XPIAN_COMPLETE_RTL_EQUIVALENT=$verified"
exit [expr {!$verified}]
