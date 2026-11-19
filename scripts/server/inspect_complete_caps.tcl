set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set_app_var target_library [list $cell_library]
set_app_var link_library [concat [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_ss_0p99v_0p99v_125c.db build/server/technology/ram_db/RAMSP128X16_ss_0p99v_0p99v_125c.db] [glob build/server/technology/platform_ram_db/*.db]]
read_ddc build/server/complete_soc_sm40_complete_v3_ss_ema2/design.ddc
current_design kwt_complete_soc
link
set stream [open reports/server/complete_soc_sm40_complete_v3_ss_ema2/pt/constraints.rpt r]
set text [read $stream]
close $stream
foreach {full pin required actual slack} [regexp -all -inline {(\S+/\S+)\s+([0-9.]+)\s+([0-9.]+)\s+(-?[0-9.]+)\s+\(VIOLATED\)} $text] {
    set cell [file dirname $pin]
    set reference [get_attribute [get_cells $cell] ref_name]
    puts "CAP_DRIVER $cell $reference required=$required actual=$actual"
    regexp {^(.*V)[0-9]+(.*)$} $reference -> prefix suffix
    puts "CAP_CHOICES [get_object_name [get_lib_cells */${prefix}*${suffix}]]"
}
exit
