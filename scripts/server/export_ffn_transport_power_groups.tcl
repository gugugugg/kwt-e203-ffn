# Native cell attributes retain precision for ordering reuse experiments.
array set group_internal {}
array set group_switching {}
array set group_leakage {}
array set group_count {}
foreach group {input weight bias shift stash row_cache accumulator fifo accelerator_other cpu itcm dtcm shared_sram fixed_peripherals other} {
    set group_internal($group) 0.0
    set group_switching($group) 0.0
    set group_leakage($group) 0.0
    set group_count($group) 0
}
foreach_in_collection cell [get_cells -hierarchical * -filter {is_hierarchical == false}] {
    set name [get_object_name $cell]
    set ref [get_attribute $cell ref_name]
    set group other
    if {[string match *scratch* $name] && [string match RAMSP* $ref]} {
        set group input
    } elseif {[string match *parameter_banks*weights* $name] && [string match RAMSP* $ref]} {
        set group weight
    } elseif {([string match *separate_bias* $name] || [string match *compact_bias_banks* $name]) && [string match RAMSP* $ref]} {
        set group bias
    } elseif {[string match *shift_memory* $name] && [string match RAMSP* $ref]} {
        set group shift
    } elseif {[string match *row_stash* $name] && [string match RAMSP* $ref]} {
        set group stash
    } elseif {[string match *core*row_cache* $name] || [string match *row_input_gate* $name]} {
        set group row_cache
    } elseif {[string match *core*accumulator* $name] || [string match *fine_accumulators* $name] || [string match *row_accumulators* $name]} {
        set group accumulator
    } elseif {[string match *core*fifo* $name]} {
        set group fifo
    } elseif {[string match *accelerator* $name]} {
        set group accelerator_other
    } elseif {[string match *u_e203_itcm_ram* $name]} {
        set group itcm
    } elseif {[string match *u_e203_dtcm_ram* $name]} {
        set group dtcm
    } elseif {[string match *u_e203_cpu* $name]} {
        set group cpu
    } elseif {[string match shared_memory/* $name]} {
        set group shared_sram
    } elseif {[string match soc/* $name]} {
        set group fixed_peripherals
    }
    set group_internal($group) [expr {$group_internal($group)+[get_attribute $cell internal_power]}]
    set group_switching($group) [expr {$group_switching($group)+[get_attribute $cell switching_power]}]
    set group_leakage($group) [expr {$group_leakage($group)+[get_attribute $cell leakage_power]}]
    incr group_count($group)
}
set stream [open $report/power_groups.json w]
puts $stream "{\"unit\":\"W\",\"source\":\"native PrimeTime leaf-cell attributes\",\"groups\":{"
set separator ""
foreach group {input weight bias shift stash row_cache accumulator fifo accelerator_other cpu itcm dtcm shared_sram fixed_peripherals other} {
    puts $stream [format {%s"%s":{"internal_w":%.17g,"switching_w":%.17g,"leakage_w":%.17g,"cells":%d}} $separator $group $group_internal($group) $group_switching($group) $group_leakage($group) $group_count($group)]
    set separator ","
}
puts $stream "\}\}"
close $stream
puts "XPIAN_NEXT_POWER_GROUPS_EXPORTED=1"
