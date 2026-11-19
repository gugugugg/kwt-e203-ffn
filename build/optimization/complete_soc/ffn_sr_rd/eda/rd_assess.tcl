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
set rd_src [get_pins -hierarchical -quiet -filter {full_name =~ */core/item_reg_*/Q* || full_name =~ */output_queue/held_count_reg_*/Q* || full_name =~ */output_queue/pending_count_reg_*/Q*}]
redirect $report/rd_paths.rpt {
    puts "RD_STARTPOINTS [sizeof_collection $rd_src]"
    foreach bank {0 1 2} {
        set rd_a [get_pins -hierarchical -quiet -filter "full_name =~ */output_queue/row_stash_${bank}__memory/macro_wrapper/macro/A*"]
        puts "RD_BANK $bank ADDRESS_PINS [sizeof_collection $rd_a]"
        foreach delay {max min} {
            report_timing -from $rd_src -to $rd_a -delay_type $delay -max_paths 3 -significant_digits 6 -transition_time -capacitance -nets
        }
    }
    foreach pattern {*/output_queue/pending_parity_reg/D */output_queue/row_stash*__gate/*/E */output_queue/pending_count_reg_*/D} {
        set rd_to [get_pins -hierarchical -quiet -filter "full_name =~ $pattern"]
        puts "RD_ENDPOINTS $pattern [sizeof_collection $rd_to]"
        if {[sizeof_collection $rd_to]} {
            foreach delay {max min} {
                report_timing -from $rd_src -to $rd_to -delay_type $delay -max_paths 3 -significant_digits 6 -transition_time -capacitance -nets
            }
        }
    }
}
puts "XPIAN_RD_ASSESSMENT_DONE setup=$assessment_setup hold=$assessment_hold"
exit
