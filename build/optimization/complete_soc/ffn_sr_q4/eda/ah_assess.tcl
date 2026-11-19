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

redirect $report/clock_gating_setup.rpt {report_constraint -clock_gating_setup -verbose -significant_digits 6}
redirect $report/clock_gating_hold.rpt {report_constraint -clock_gating_hold -verbose -significant_digits 6}
set ah_acc_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/accumulator_reg_*/D}]
set ah_acc_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/accumulator_reg_*/Q}]
set ah_input [get_pins -hierarchical -quiet -filter {full_name =~ */core/jp_input_return_reg_*/Q*}]
set ah_weight [get_pins -hierarchical -quiet -filter {full_name =~ */core/parameter_banks*__weights/*/macro/Q*}]
set ah_gate [get_pins -hierarchical -quiet -filter {full_name =~ */core/*pair_gate_acc_gate/cell_gate/E}]
redirect $report/ah_paths.rpt {
    puts "Q4_OBJECTS [sizeof_collection $ah_acc_d] [sizeof_collection $ah_acc_q] [sizeof_collection $ah_input] [sizeof_collection $ah_weight] [sizeof_collection $ah_gate]"
    foreach entry [list [list input $ah_input] [list weight $ah_weight] [list feedback $ah_acc_q]] {
        lassign $entry label pins
        puts "Q4_PATH_GROUP $label"
        if {[sizeof_collection $pins] && [sizeof_collection $ah_acc_d]} {
            foreach delay {max min} {
                report_timing -through $pins -to $ah_acc_d -delay_type $delay -max_paths 4 -slack_lesser_than 1000000 -significant_digits 6 -path_type full_clock_expanded -transition_time -capacitance -nets
            }
        }
    }
    puts "Q4_PATH_GROUP gate"
    if {[sizeof_collection $ah_gate]} {
        foreach delay {max min} {
            report_timing -to $ah_gate -delay_type $delay -max_paths 4 -slack_lesser_than 1000000 -significant_digits 6
        }
    }
}

set q4_bias [get_pins -hierarchical -quiet -filter {full_name =~ */core/compact_bias_banks*/*/Q* || full_name =~ */core/*shift_memory*/Q*}]
set q4_quant [get_pins -hierarchical -quiet -filter {full_name =~ */core/q4_quantizers*/*result*}]
set q4_room [get_pins -hierarchical -quiet -filter {full_name =~ */core/output_queue/row?_room}]
redirect $report/q4_interface_paths.rpt {
    foreach entry [list [list bias_shift $q4_bias] [list quantizer $q4_quant] [list acceptance $q4_room]] {
        lassign $entry label pins
        puts "Q4_INTERFACE $label [sizeof_collection $pins]"
        if {[sizeof_collection $pins]} {
            foreach delay {max min} {
                report_timing -through $pins -delay_type $delay -max_paths 4 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets
            }
        }
    }
}

puts "XPIAN_Q4_ASSESSMENT_DONE setup=$assessment_setup hold=$assessment_hold"
exit
