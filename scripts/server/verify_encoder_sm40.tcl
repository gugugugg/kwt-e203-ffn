set synopsys_auto_setup true
set tag $env(XPIAN_TAG)
set report reports/server/encoder_sm40_$tag/formality
file mkdir $report
set_svf build/server/encoder_sm40_$tag/design.svf
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
read_db -technology_library $cell_library
foreach memory {RAMSP1024X16 RAMSP128X16} {
    read_db -technology_library build/server/technology/ram_db/${memory}_ss_0p99v_0p99v_125c.db
}
set_app_var search_path [concat [list [pwd] [file normalize rtl/encoder]] $search_path]
set sources [list rtl/technology/kwt_sram_sm40.sv rtl/technology/kwt_encoder_sram_sm40.sv rtl/kwt_spmem16.sv rtl/public_encoder/kwt_encoder_accelerator.sv]
foreach source [glob rtl/encoder/*.sv] {
    if {[file tail $source] ne "kwt_encoder_sram16x128.sv"} {lappend sources $source}
}
set sources [concat $sources [glob rtl/encoder_bus/*.sv]]
set absolute_sources {}
foreach source $sources {lappend absolute_sources [file normalize $source]}
read_sverilog -r $absolute_sources
set_top r:/WORK/kwt_encoder_accelerator
read_verilog -i [file normalize build/server/encoder_sm40_$tag/netlist.v]
set_top i:/WORK/kwt_encoder_accelerator
match
set verified [verify]
redirect $report/failing.rpt {report_failing_points}
redirect $report/unmatched.rpt {report_unmatched_points}
puts "XPIAN_ENCODER_FORMALITY_PASSED=$verified"
exit [expr {!$verified}]
