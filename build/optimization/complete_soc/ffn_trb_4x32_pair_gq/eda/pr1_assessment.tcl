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
set writer [get_pins -hierarchical -quiet -filter {full_name =~ */core/retire_index_reg*/Q* || full_name =~ */core/out_word_reg*/Q* || full_name =~ */core/out_count_reg*/Q*}]
set output_macros [get_pins -hierarchical -quiet -filter {(full_name =~ shared_memory/memory/banks_4*/* || full_name =~ shared_memory/memory/banks_5*/* || full_name =~ shared_memory/memory/banks_6*/* || full_name =~ shared_memory/memory/banks_7*/*) && (full_name =~ */A* || full_name =~ */D* || full_name =~ */CEN || full_name =~ */GWEN)}]
set operands [get_pins -hierarchical -quiet -filter {full_name =~ */core/operands_reg*/Q*}]
set weight_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/weight_columns_*__memory/Q*}]
set acc [get_pins -hierarchical -quiet -filter {full_name =~ */core/*acc_a_reg*/D || full_name =~ */core/*acc_b_reg*/D}]
set quant [get_pins -hierarchical -quiet -filter {full_name =~ */core/quant_data_reg*/Q*}]
set scratch_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/result_memory_*__memory/D*}]
set scratch_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/result_memory_*__memory/Q*}]
set fifo_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/out_word_reg*/D}]
redirect $report/pr1_paths.rpt {
    foreach group [list [list result_writer_to_shared_bank $writer $output_macros] [list operands_to_mac $operands $acc] [list weight_to_mac $weight_q $acc] [list quant_to_scratch $quant $scratch_d] [list scratch_to_fifo $scratch_q $fifo_d]] {
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

set lane_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/*acc_a_reg*/Q* || full_name =~ */core/*acc_b_reg*/Q*}]
set quant_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/quant_data_reg*/D}]
set ingress_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/ingress_reg*/D}]
redirect $report/pair_candidate_paths.rpt {
    puts "CANDIDATE_QUANT_ENDPOINTS [sizeof_collection $lane_q] [sizeof_collection $quant_d]"
    puts "CANDIDATE_INGRESS_ENDPOINTS [sizeof_collection $ingress_d]"
    foreach delay {max min} {
        report_timing -from $lane_q -to $quant_d -delay_type $delay -max_paths 10 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets -transition_time -capacitance
        report_timing -to $ingress_d -delay_type $delay -max_paths 10 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets -transition_time -capacitance
    }
}

puts "XPIAN_PR1_ASSESSMENT_DONE setup=$assessment_setup hold=$assessment_hold"
exit
