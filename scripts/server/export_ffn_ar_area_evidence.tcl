# Record actual separable state cells after this candidate's normal update_power.
set car_stream [open $report/ar_area_state_cells.tsv w]
puts $car_stream "role\tcell\tref_name\tarea_um2\tinternal_w\tswitching_w\tleakage_w\ttotal_w"
set car_count 0
foreach_in_collection car_cell [get_cells -hierarchical * -filter {is_hierarchical == false}] {
    set car_name [get_object_name $car_cell]
    set car_ref [get_attribute $car_cell ref_name]
    set car_role ""
    if {[string match */core/accumulator_reg_* $car_name]} {
        set car_role accumulator_state
    } elseif {[string match */core/shifts_reg_* $car_name]} {
        set car_role shift_state
    } elseif {[string match CLKLANA* $car_ref] && [string match */core/*pair_gate_shift_gate/cell_gate $car_name]} {
        set car_role shift_pair_clock_gate
    } elseif {[string match CLKLANA* $car_ref] && [string match */core/jp_mac_lanes_*pair_gate_acc_gate/cell_gate $car_name]} {
        set car_role accumulator_pair_clock_gate
    } elseif {[string match */dma_frontend/loading_dma/source_remaining_reg_* $car_name]} {
        set car_role DMA_source_remaining
    } elseif {[string match */dma_frontend/loading_dma/dest_remaining_reg_* $car_name]} {
        set car_role DMA_destination_remaining
    } elseif {[string match */dma_frontend/loading_dma/pd_count_reg_* $car_name]} {
        set car_role DMA_pending_count
    }
    if {$car_role eq ""} {continue}
    puts $car_stream [join [list $car_role $car_name $car_ref \
        [ap_evidence_attr $car_cell cell area] \
        [ap_evidence_attr $car_cell cell internal_power] \
        [ap_evidence_attr $car_cell cell switching_power] \
        [ap_evidence_attr $car_cell cell leakage_power] \
        [ap_evidence_attr $car_cell cell total_power]] "\t"]
    incr car_count
}
close $car_stream
puts "AR_AREA_STATE_EVIDENCE_DONE cells=$car_count"
