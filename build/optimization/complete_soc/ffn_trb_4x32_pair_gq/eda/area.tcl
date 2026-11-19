array set areas {accelerator 0 cpu 0 shared_sram 0 shared_interface 0 fixed_peripherals 0}
array set counts {}
array set reference_areas {}
current_design kwt_complete_soc
set leaf_cells [get_cells -hierarchical * -filter "is_hierarchical == false"]
puts "XPIAN_PLATFORM_LEAF_CELLS=[sizeof_collection $leaf_cells]"
foreach_in_collection cell $leaf_cells {
    set name [get_object_name $cell]
    set reference [get_attribute $cell ref_name]
    if {![info exists reference_areas($reference)]} {
        if {$reference eq "**logic_1**" || $reference eq "**logic_0**"} {
            set reference_areas($reference) 0
        } else {
            set reference_areas($reference) [get_attribute [get_lib_cells */$reference] area]
        }
    }
    set area $reference_areas($reference)
    if {[string match soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/* $name]} {set part accelerator} elseif {[string match soc/u_e203_subsys_main/u_e203_cpu_top/* $name]} {
        set part cpu
    } elseif {[string match shared_memory/memory/* $name] && [string match RAMSP* $reference]} {set part shared_sram} elseif {[string match shared_memory/* $name]} {
        set part shared_interface
    } else {set part fixed_peripherals}
    set areas($part) [expr {$areas($part)+$area}]
    if {[string match RAMSP* $reference] || [string match ROM* $reference]} {
        if {![info exists counts($reference)]} {set counts($reference) 0}
        incr counts($reference)
    }
}
set stream [open $report/area_partitions.json w]
puts $stream "\{"
set sum 0
foreach part [lsort [array names areas]] {
    puts $stream [format {  "%s_um2": %.9f,} $part $areas($part)]
    set sum [expr {$sum+$areas($part)}]
}
puts $stream [format {  "total_um2": %.9f,} $sum]
puts $stream [format {  "accelerator_budget_including_shared_interface_mm2": %.9f,} [expr {($areas(accelerator)+$areas(shared_interface))/1000000.0}]]
puts $stream "  \"macros\": \{"
set names [lsort [array names counts]]
foreach reference $names {
    set comma ","
    if {$reference eq [lindex $names end]} {set comma ""}
    puts $stream [format {    "%s": %d%s} $reference $counts($reference) $comma]
}
puts $stream "  \}\n\}"
close $stream
