set mgpr_macros [get_cells -hierarchical -quiet -filter {(full_name =~ */core/weight_columns*memory || full_name =~ */core/input_banks*memory || full_name =~ */core/result_banks*memory) && (ref_name == RAMSP128X16 || ref_name == RAMSP1024X16)}]
set mgpr_gate_e [get_pins -hierarchical -quiet -filter {full_name =~ */core/*private_gate*/cell_gate/E}]
if {[sizeof_collection $mgpr_macros] != 40 || [sizeof_collection $mgpr_gate_e] != 40} {
    error "Expected 40 actual private macros and enable endpoints"
}
set mgpr_inputs [get_pins -quiet -of_objects $mgpr_macros -filter {direction == in && full_name !~ */CLK}]
set mgpr_outputs [get_pins -quiet -of_objects $mgpr_macros -filter {direction == out}]
set mgpr_registers [all_registers]
set mgpr_result_macros [filter_collection $mgpr_macros {full_name =~ */core/result_banks*memory}]
set mgpr_result_q [get_pins -quiet -of_objects $mgpr_result_macros -filter {direction == out}]
set mgpr_result_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/out_word_reg*/D}]
lappend paths [list private_input $mgpr_registers $mgpr_inputs] \
    [list private_output $mgpr_outputs $mgpr_registers] \
    [list private_enable $mgpr_registers $mgpr_gate_e] \
    [list result_to_queue $mgpr_result_q $mgpr_result_d]
