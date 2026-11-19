# Use the preceding PrimeTime violations to strengthen only their driving cells.
set previous [file tail [file dirname $env(XPIAN_DRC_FROM)]]
set stream [open reports/server/${previous}/pt/constraints.rpt r]
set violations [read $stream]
close $stream
array set targets {}
# Report pin names and numbers can occupy separate lines.
set split_at [string first max_transition $violations]
set sections [list cap [string range $violations 0 [expr {$split_at-1}]] slew [string range $violations $split_at end]]
foreach {section text} $sections {
    foreach {row pin required actual slack} [regexp -all -inline {(\S+/\S+)\s+([0-9.]+)\s+([0-9.]+)\s+(-?[0-9.]+)\s+\(VIOLATED\)} $text] {
        set object [get_pins $pin]
        if {[get_attribute $object direction] eq "out"} {
            set drivers $object
        } else {
            set drivers [filter_collection [all_connected -leaf [get_nets -of_objects $object]] {direction == out}]
        }
        foreach_in_collection driver $drivers {
            set name [get_object_name $driver]
            set cell [get_cells -of_objects $driver]
            set ref [get_attribute $cell ref_name]
            set library_pin [get_lib_pins */${ref}/[file tail $name]]
            set old_cap [get_attribute $library_pin max_capacitance]
            if {$section eq "cap"} {set target $actual} else {set target [expr {$old_cap*$actual/$required}]}
            if {![info exists targets($name)] || $target > $targets($name)} {set targets($name) $target}
        }
    }
}
set resized 0
set buffered 0
foreach name [lsort [array names targets]] {
    set cell [get_cells -of_objects [get_pins $name]]
    set ref [get_attribute $cell ref_name]
    set output [file tail $name]
    set old_pin [get_lib_pins */${ref}/$output]
    set old_function [get_attribute $old_pin function]
    regexp {^(.*V)[0-9]+(.*)$} $ref -> prefix suffix
    set chosen ""
    set best_area 1e30
    set best_cap 1e30
    foreach_in_collection choice [get_lib_cells */${prefix}*${suffix}] {
        set choice_name [get_object_name $choice]
        set pin [get_lib_pins $choice_name/$output]
        set cap [get_attribute $pin max_capacitance]
        set area [get_attribute $choice area]
        if {$cap >= $targets($name) && [get_attribute $pin function] eq $old_function &&
            ($area < $best_area || ($area == $best_area && $cap < $best_cap))} {
            set chosen $choice_name
            set best_area $area
            set best_cap $cap
        }
    }
    if {$chosen ne ""} {
        puts "XPIAN_ELECTRICAL_SIZE $name $ref -> $chosen required_capacity=$targets($name)"
        size_cell $cell [get_lib_cells $chosen]
        incr resized
    } else {
        foreach_in_collection choice [get_lib_cells */CLKBUF*_12TR40] {
            set choice_name [get_object_name $choice]
            set pins [get_lib_pins -of_objects $choice -filter {direction == out}]
            set cap [get_attribute $pins max_capacitance]
            set area [get_attribute $choice area]
            if {$cap >= $targets($name) && ($area < $best_area || ($area == $best_area && $cap < $best_cap))} {
                set chosen $choice_name
                set best_area $area
                set best_cap $cap
            }
        }
        puts "XPIAN_ELECTRICAL_BUFFER $name $chosen required_capacity=$targets($name)"
        insert_buffer [get_pins $name] [get_lib_cells $chosen]
        incr buffered
    }
}
puts "XPIAN_ELECTRICAL_REPAIR resized=$resized buffered=$buffered"
