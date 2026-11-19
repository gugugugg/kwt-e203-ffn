set tag $env(XPIAN_TAG)
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set_app_var target_library [list $cell_library]
set_app_var link_library [concat [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_ss_0p99v_0p99v_125c.db build/server/technology/ram_db/RAMSP128X16_ss_0p99v_0p99v_125c.db] [glob build/server/technology/platform_ram_db/*.db]]
read_ddc build/server/complete_soc_sm40_$tag/design.ddc
current_design kwt_complete_soc
link
set stream [open reports/server/complete_soc_sm40_$tag/pt/constraints.rpt r]
set text [read $stream]
close $stream
set stop [string first max_transition $text]
if {$stop >= 0} {set text [string range $text 0 [expr {$stop-1}]]}
array set seen {}
foreach {full pin required actual slack} [regexp -all -inline {(\S+/\S+)\s+([0-9.]+)\s+([0-9.]+)\s+(-?[0-9.]+)\s+\(VIOLATED\)} $text] {
    set cell [file dirname $pin]
    set reference [get_attribute [get_cells $cell] ref_name]
    if {[info exists seen($reference)]} {continue}
    set seen($reference) 1
    puts "DRC_REF $reference output=[file tail $pin] required=$required actual=$actual"
    regexp {^(.*V)[0-9]+(.*)$} $reference -> prefix suffix
    foreach_in_collection choice [get_lib_cells */${prefix}*${suffix}] {
        set name [get_object_name $choice]
        set output [get_lib_pins $name/[file tail $pin]]
        puts "DRC_CHOICE $name cap=[get_attribute $output max_capacitance] area=[get_attribute $choice area]"
    }
}
puts "BUFFER_CHOICES [get_object_name [get_lib_cells */CLKBUF*12TR40]]"
redirect reports/optimization/insert_buffer_help.txt {man insert_buffer}
redirect reports/optimization/net_attributes.txt {list_attributes -application -class net}
exit
