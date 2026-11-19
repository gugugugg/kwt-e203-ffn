set synopsys_auto_setup true
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
read_db -technology_library $cell_library
foreach memory {RAMSP1024X16 RAMSP128X16} {
    read_db -technology_library build/server/technology/ram_db/${memory}_ss_0p99v_0p99v_125c.db
}
set reference_tag ss_requant64_c2c_ema2
if {[info exists env(XPIAN_REFERENCE_TAG)]} {set reference_tag $env(XPIAN_REFERENCE_TAG)}
read_verilog -r build/server/ffn_sm40_$reference_tag/netlist.v
set_top r:/WORK/kwt_icb_ffn_channel
set implementation_tag ss_requant64_load_ema2
if {[info exists env(XPIAN_TAG)]} {set implementation_tag $env(XPIAN_TAG)}
read_verilog -i build/server/ffn_sm40_$implementation_tag/netlist.v
set_top i:/WORK/kwt_icb_ffn_channel
match
set verified [verify]
report_failing_points
report_unmatched_points
exit [expr {!$verified}]
