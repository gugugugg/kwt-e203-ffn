set synopsys_auto_setup true
set tag $env(XPIAN_TAG)
set report reports/server/unified_platform_sm40_$tag/formality
file mkdir $report
set_host_options -max_cores 8
set_svf [list build/server/unified_platform_sm40_dual_v1_ss_ema2/design.svf build/server/unified_platform_sm40_dual_v2_ss_ema2/design.svf build/server/unified_platform_sm40_dual_v3_ss_ema2/design.svf]
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
read_db -technology_library $cell_library
foreach memory {RAMSP1024X16 RAMSP128X16} {
    read_db -technology_library build/server/technology/ram_db/${memory}_ss_0p99v_0p99v_125c.db
}
foreach library [glob build/server/technology/platform_ram_db/*.db] {read_db -technology_library $library}
set upstream [file normalize build/server/official_2025/e203_hbirdv2-master/rtl/e203]
set_app_var search_path [concat [list [pwd] [file normalize rtl/encoder] [file normalize rtl/public_encoder] [file normalize build/unified_public] $upstream/core $upstream/perips $upstream/perips/apb_i2c] $search_path]
set stream [open build/unified_public/files.f r]
set sources {}
foreach source [split [read $stream] "\n"] {
    if {$source eq "" || [string match tb/* $source] || [string match /storage1/* $source] || [string match */mem_gen/* $source] || [string match */scc40nll_vhsc40_rvt.v $source] || [string match */physical_cpu_soc.sv $source] || [string match */physical_tb.sv $source]} {continue}
    lappend sources [file normalize $source]
}
close $stream
read_sverilog -r $sources
set_top r:/WORK/kwt_encoder_platform
read_verilog -i [file normalize build/server/unified_platform_sm40_$tag/netlist.v]
set_top i:/WORK/kwt_encoder_platform
match
set verified [verify]
redirect $report/failing.rpt {report_failing_points}
redirect $report/unmatched.rpt {report_unmatched_points}
puts "XPIAN_ENCODER_FORMALITY_PASSED=$verified"
exit [expr {!$verified}]
