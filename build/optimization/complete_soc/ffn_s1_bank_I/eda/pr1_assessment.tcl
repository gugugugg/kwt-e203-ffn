set corner ss
if {[info exists env(XPIAN_CORNER)]} {set corner $env(XPIAN_CORNER)}
set tag ${corner}_ema2
if {[info exists env(XPIAN_TAG)]} {set tag $env(XPIAN_TAG)}
set report reports/server/complete_soc_sm40_$tag/pt
file mkdir $report
if {$corner eq "ss"} {
    set cell_name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db
    set ram_corner ss_0p99v_0p99v_125c
} else {
    set cell_name scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db
    set ram_corner tt_1p10v_1p10v_25c
}
set cell_library [exec find build/server/technology -name $cell_name]
set link_path [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_${ram_corner}.db build/server/technology/ram_db/RAMSP128X16_${ram_corner}.db]
set link_path [concat $link_path [glob build/server/technology/platform_ram_db/*.db]]
read_verilog build/server/complete_soc_sm40_$tag/netlist.v
current_design kwt_complete_soc
link_design
source constraints/complete_soc.sdc
puts "XPIAN_ASSESSMENT_SDC=constraints/complete_soc.sdc"
update_timing
redirect $report/clocks.rpt {report_clock}
redirect $report/units.rpt {report_units}
redirect $report/design.rpt {report_design}
redirect $report/check_timing.rpt {check_timing -verbose}
redirect $report/coverage.rpt {report_analysis_coverage}
redirect $report/timing_max.rpt {report_timing -delay_type max -max_paths 10 -slack_lesser_than 1000000 -significant_digits 6 -path_type full_clock_expanded -input_pins -nets -transition_time -capacitance}
redirect $report/timing_min.rpt {report_timing -delay_type min -max_paths 10 -slack_lesser_than 1000000 -significant_digits 6}
redirect $report/constraints.rpt {report_constraint -all_violators -significant_digits 6}
set path [get_timing_paths -delay_type max -max_paths 1 -slack_lesser_than 1000000]
puts "XPIAN_SM40_MAX_SLACK_NS=[get_attribute $path slack]"
puts "XPIAN_SM40_START=[get_object_name [get_attribute $path startpoint]]"
puts "XPIAN_SM40_END=[get_object_name [get_attribute $path endpoint]]"
set assessment_setup [get_attribute $path slack]
set assessment_hold [get_attribute [get_timing_paths -delay_type min -max_paths 1 -slack_lesser_than 1000000] slack]
puts "XPIAN_ASSESSMENT_HOLD_SLACK_NS=$assessment_hold"

redirect $report/clock_gating_setup.rpt {report_constraint -clock_gating_setup -verbose -significant_digits 9}
redirect $report/clock_gating_hold.rpt {report_constraint -clock_gating_hold -verbose -significant_digits 9}
set input_q [get_pins -hierarchical -quiet -filter {full_name =~ */accelerator/controller/core/ap_input_rows*/*/Q*}]
set input_d [get_pins -hierarchical -quiet -filter {full_name =~ */accelerator/controller/core/jp_input_return_reg_*/D}]
set weight_q [get_pins -hierarchical -quiet -filter {full_name =~ */accelerator/controller/core/parameter_banks*/*/Q*}]
set weight_d [get_pins -hierarchical -quiet -filter {full_name =~ */accelerator/controller/core/operand_weight_reg_*/D}]
set operand_q [get_pins -hierarchical -quiet -filter {full_name =~ */accelerator/controller/core/jp_input_return_reg_*/Q* || full_name =~ */accelerator/controller/core/operand_weight_reg_*/Q*}]
set acc_q [get_pins -hierarchical -quiet -filter {full_name =~ */accelerator/controller/core/accumulator_reg_*/Q*}]
set acc_d [get_pins -hierarchical -quiet -filter {full_name =~ */accelerator/controller/core/accumulator_reg_*/D}]
set macro_q [get_pins -hierarchical -quiet -filter {full_name =~ shared_memory/memory/*/Q*}]
set bank_q [get_pins -hierarchical -quiet -filter {full_name =~ shared_memory/memory/read_bank_reg_*/Q*}]
set slot_d [get_pins -hierarchical -quiet -filter {full_name =~ */loading_dma/pd_slot_reg_*/D}]
set fast_q [get_pins -hierarchical -quiet -filter {full_name =~ shared_memory/pending_fast_access_reg*/Q* || full_name =~ shared_memory/pending_reg*/Q*}]
set ram_cmd [get_pins -hierarchical -quiet -filter {full_name =~ shared_memory/memory/*/CEN || full_name =~ shared_memory/memory/*/A*}]
set prefix_q [get_pins -hierarchical -quiet -filter {full_name =~ shared_memory/input_committed_reg*/Q*}]
set input_wr_q [get_pins -hierarchical -quiet -filter {full_name =~ */loading_dma/pd_slot_reg_*/Q* || full_name =~ */core/input_write*reg*/Q* || full_name =~ */controller/load_address_reg_*/Q*}]
set input_wr_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/ap_input_rows*/*/D* || full_name =~ */core/ap_input_rows*/*/A* || full_name =~ */core/ap_input_rows*/*/WEN* || full_name =~ */core/ap_input_rows*/*/CEN}]

set result_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/output_queue/row_stash*/*/Q*}]
set held_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/output_queue/held_data_reg*/D}]
set held_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/output_queue/held_data_reg*/Q*}]
set pio_d [get_pins -hierarchical -quiet -filter {full_name =~ */controller/pio_rsp_rdata_reg*/D || full_name =~ */controller/*rsp*data*reg*/D || full_name =~ */loading_dma/pd_slot_reg*/D}]
set held_count_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/output_queue/held_count_reg*/Q* || full_name =~ */core/output_queue/pending_count_reg*/Q*}]
set result_a [get_pins -hierarchical -quiet -filter {full_name =~ */core/output_queue/row_stash*/*/A* || full_name =~ */core/output_queue/row_stash*/*/CEN}]
set result_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/output_queue/row_stash*/*/D*}]
set seed_bias_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/compact_bias_banks*/*/Q*}]
set shift_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/jp_shift_return_reg*/Q*}]
set shift_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/shifts_reg*/D}]
set generation_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/output_queue/generation_state_reg*/Q*}]
set shift_macro_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/shift_memory/*/Q*}]
set shadow_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/q16_seed_shadow_reg*/D}]
set shadow_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/q16_seed_shadow_reg*/Q*}]
set pf2_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/tile_reg*/Q* || full_name =~ */core/lane_reg*/Q* || full_name =~ */core/state_reg*/Q*}]
set operand_addresses [get_pins -hierarchical -quiet -filter {full_name =~ */core/ap_input_rows*/*/A* || full_name =~ */core/parameter_banks*/weights/*/A*}]

set parameter_prefix_q [get_pins -hierarchical -quiet -filter {full_name =~ shared_memory/parameter_committed_reg*/Q* || full_name =~ shared_memory/shift_committed_reg*/Q*}]
set stream_macro [get_pins -hierarchical -quiet -filter {full_name =~ shared_memory/memory/banks_8*/*CEN || full_name =~ shared_memory/memory/banks_9*/*CEN || full_name =~ shared_memory/memory/banks_10*/*CEN || full_name =~ shared_memory/memory/banks_14*/*CEN}]
redirect $report/pr1_paths.rpt {
    foreach group [list [list input_to_stage $input_q $input_d] [list weight_to_stage $weight_q $weight_d] [list operands_to_accumulator $operand_q $acc_d] [list feedback_to_accumulator $acc_q $acc_d] [list macro_to_slot $macro_q $slot_d] [list bank_to_slot $bank_q $slot_d] [list turnover_to_macro $fast_q $ram_cmd] [list packed_input_to_macro $input_wr_q $input_wr_d] [list result_sram_to_ring $result_q $held_d] [list ring_to_pio $held_q $pio_d] [list reservation_to_stash $held_count_q $result_a] [list quantization_to_stash $acc_q $result_d] [list bias_reseed $seed_bias_q $acc_d] [list generation_to_stash $generation_q $result_a] [list bias_to_shadow $seed_bias_q $shadow_d] [list shift_to_shadow $shift_q $shadow_d] [list shadow_to_accumulator $shadow_q $acc_d] [list shadow_to_shift $shadow_q $shift_d] [list prefetch_address $pf2_q $operand_addresses] [list input_prefix_to_shared_port $prefix_q $ram_cmd] [list parameter_prefix_to_stream_bank $parameter_prefix_q $stream_macro]] {
        lassign $group label sources targets
        puts "PR1_PATH_GROUP $label [sizeof_collection $sources] [sizeof_collection $targets]"
        if {[sizeof_collection $sources] && [sizeof_collection $targets]} {
            foreach delay {max min} {
                puts "PR1_PATH_DELAY $delay"
                report_timing -from $sources -to $targets -delay_type $delay -max_paths 5 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets -transition_time -capacitance
            }
        }
    }
}
puts "XPIAN_PR1_ASSESSMENT_DONE setup=$assessment_setup hold=$assessment_hold"
exit
