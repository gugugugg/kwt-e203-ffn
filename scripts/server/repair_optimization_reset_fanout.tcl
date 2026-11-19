# Strengthen only buffer cells on the observed failing reset recovery paths.
set stream [open $env(XPIAN_REPAIR_TIMING_RPT) r]
set timing_text [read $stream]
close $stream
array set reset_targets {}
foreach {row name reference} [regexp -all -inline {(\S+)/Z\s+\((CLKBUFV[0-9]+_12TR40)\)} $timing_text] {
    set reset_targets($name) $reference
}
set resized 0
foreach name [lsort [array names reset_targets]] {
    set cell [get_cells $name]
    set reference [get_attribute $cell ref_name]
    set pin [get_lib_pins */${reference}/Z]
    set required [expr {2.0*[get_attribute $pin max_capacitance]}]
    set function [get_attribute $pin function]
    set best_area 1e30
    set selected ""
    foreach_in_collection choice [get_lib_cells */CLKBUF*_12TR40] {
        set candidate [get_object_name $choice]
        set output [get_lib_pins $candidate/Z]
        set area [get_attribute $choice area]
        if {[get_attribute $output function] eq $function &&
            [get_attribute $output max_capacitance] >= $required && $area < $best_area} {
            set selected $candidate
            set best_area $area
        }
    }
    if {$selected eq ""} {error "No stronger same-function reset buffer for $name"}
    puts "XPIAN_RESET_FANOUT_SIZE $name $reference -> $selected"
    size_cell $cell [get_lib_cells $selected]
    incr resized
}
if {$resized == 0} {error "No buffer cells found in the observed failing reset paths"}
puts "XPIAN_RESET_FANOUT_REPAIR resized=$resized"
