# Same proven leaf attributes as the accepted normal group exporter.
set stream [open $report/private_leaf_power.tsv w]
puts $stream "cell\tref_name\tarea_um2\tinternal_w\tswitching_w\tleakage_w"
foreach_in_collection cell [get_cells -hierarchical * -filter {is_hierarchical == false}] {
    set name [get_object_name $cell]
    if {![string match *accelerator* $name] && ![string match shared_memory/* $name]} {continue}
    puts $stream [format "%s\t%s\t%.17g\t%.17g\t%.17g\t%.17g" $name \
        [get_attribute $cell ref_name] [get_attribute $cell area] \
        [get_attribute $cell internal_power] [get_attribute $cell switching_power] [get_attribute $cell leakage_power]]
}
close $stream
puts "JOINT_POWER_PRIVATE_LEAVES_EXPORTED=1"
