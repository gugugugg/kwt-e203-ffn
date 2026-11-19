# Supplement the normal candidate update_power with separable shift-boundary cells.
set wen_stream [open $report/c_final_energy_shift_cells.tsv w]
puts $wen_stream "role\tcell\tref_name\tarea_um2\tinternal_w\tswitching_w\tleakage_w\ttotal_w"
set wen_count 0
foreach_in_collection wen_cell [get_cells -hierarchical * -filter {is_hierarchical == false}] {
    set wen_name [get_object_name $wen_cell]
    set wen_ref [get_attribute $wen_cell ref_name]
    set wen_role ""
    if {[string match *accelerator*core*jp_shift_return_reg_* $wen_name]} {
        set wen_role shift_return_latch
    } elseif {[string match CLKLANA* $wen_ref] && [string match */core/gate_shift_gate/cell_gate $wen_name]} {
        set wen_role shift_macro_clock_gate
    } elseif {[string match *accelerator*core*shifts_reg* $wen_name]} {
        set wen_role shift_state_register
    } elseif {[string match CLKLANA* $wen_ref] && ([string match */core/jp_mac_lanes_*pair_gate_shift_gate/cell_gate $wen_name] || [string match */core/ss_shift_columns_*pair_gate_shift_gate/cell_gate $wen_name])} {
        set wen_role pair_shift_state_clock_gate
    } elseif {$wen_ref eq "RAMSP128X16" && [string match *accelerator*core*shift_memory* $wen_name]} {
        set wen_role shift_macro
    }
    if {$wen_role eq ""} {continue}
    puts $wen_stream [join [list $wen_role $wen_name $wen_ref \
        [ap_evidence_attr $wen_cell cell area] \
        [ap_evidence_attr $wen_cell cell internal_power] \
        [ap_evidence_attr $wen_cell cell switching_power] \
        [ap_evidence_attr $wen_cell cell leakage_power] \
        [ap_evidence_attr $wen_cell cell total_power]] "\t"]
    incr wen_count
}
close $wen_stream
puts "C_FINAL_ENERGY_SHIFT_EVIDENCE_DONE cells=$wen_count"
