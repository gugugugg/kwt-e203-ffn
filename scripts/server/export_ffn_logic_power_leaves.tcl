# Missing case-one evidence only, using the existing native leaf/source interfaces.
set leaf_stream [open $report/private_leaf_power.tsv w]
set net_stream [open $report/private_output_sources.tsv w]
puts $leaf_stream "cell\tref_name\tarea_um2\tinternal_w\tswitching_w\tleakage_w"
puts $net_stream "driver_cell\tdriver_pin\tsegment\tstatic_probability_native\ttoggle_rate_native"
array set lp_seen_net {}
foreach_in_collection cell [get_cells -hierarchical * -filter {is_hierarchical == false}] {
    set name [get_object_name $cell]
    if {![string match *accelerator* $name] && ![string match shared_memory/* $name]} {continue}
    puts $leaf_stream [format "%s\t%s\t%.17g\t%.17g\t%.17g\t%.17g" $name \
        [get_attribute $cell ref_name] [get_attribute $cell area] [get_attribute $cell internal_power] \
        [get_attribute $cell switching_power] [get_attribute $cell leakage_power]]
    foreach_in_collection pin [get_pins -of_objects $cell -filter {direction == out}] {
        set attached [get_attribute $pin net]
        if {[sizeof_collection $attached] == 0} {continue}
        foreach_in_collection net [get_nets -segments -of_objects $pin] {
            set net_name [get_object_name $net]
            if {[info exists lp_seen_net($net_name)]} {continue}
            set lp_seen_net($net_name) 1
            puts $net_stream [join [list $name [get_object_name $pin] $net_name \
                [get_switching_activity -static_probability $net] [get_switching_activity -toggle_rate $net]] "\t"]
        }
    }
}
close $leaf_stream
close $net_stream
set stream [open $report/public_clock_root.tsv w]
puts $stream "cell\tref_name\tarea_um2\tinternal_w\tswitching_w\tleakage_w"
set roots [get_cells -quiet {soc/u_e203_subsys_main/u_e203_subsys_hclkgen/U3}]
foreach_in_collection cell $roots {
    puts $stream [format "%s\t%s\t%.17g\t%.17g\t%.17g\t%.17g" [get_object_name $cell] \
        [get_attribute $cell ref_name] [get_attribute $cell area] [get_attribute $cell internal_power] \
        [get_attribute $cell switching_power] [get_attribute $cell leakage_power]]
}
close $stream
puts "LOGIC_POWER_PRIVATE_LEAVES_EXPORTED=1"
