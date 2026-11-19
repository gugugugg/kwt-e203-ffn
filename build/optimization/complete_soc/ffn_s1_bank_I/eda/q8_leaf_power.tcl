# Report the quantizers and private generation controls separately from the
# standard whole-SoC groups. Leaves outside these cones retain their old group.
foreach group {requantizers result_control input_bank_control seed_shadow} {
    set q8_cells($group) 0
    foreach component {internal switching leakage} {
        set q8_w($group,$component) 0.0
    }
}
foreach_in_collection cell [get_cells -hierarchical * -filter {is_hierarchical == false}] {
    set path [get_object_name $cell]
    set ref [get_attribute $cell ref_name]
    if {[string match */core/quant_rows*/* $path]} {
        set group requantizers
    } elseif {[string match */core/q16_seed_shadow_reg* $path] || [string match */core/q16_shadow_pairs*/* $path]} {
        set group seed_shadow
    } elseif {[string match */core/output_queue/* $path] && ![string match RAMSP* $ref]} {
        set group result_control
    } elseif {[string match */core/ap_input_rows*/* $path] && ![string match RAMSP* $ref]} {
        set group input_bank_control
    } else {
        continue
    }
    incr q8_cells($group)
    foreach component {internal switching leakage} {
        set q8_w($group,$component) [expr {$q8_w($group,$component) + [get_attribute $cell ${component}_power]}]
    }
}
set q8_stream [open $report/q8_leaf_power.json w]
puts $q8_stream [format {%c"unit":"W","groups":%c} 123 123]
set q8_separator {}
foreach group {requantizers result_control input_bank_control seed_shadow} {
    puts $q8_stream [format {%s"%s":{"internal_w":%.17g,"switching_w":%.17g,"leakage_w":%.17g,"cells":%d}} $q8_separator $group $q8_w($group,internal) $q8_w($group,switching) $q8_w($group,leakage) $q8_cells($group)]
    set q8_separator ,
}
puts $q8_stream "\}\}"
close $q8_stream
