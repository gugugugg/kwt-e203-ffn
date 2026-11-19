set corner ss
if {[info exists env(XPIAN_CORNER)]} {set corner $env(XPIAN_CORNER)}
set tag ${corner}_ema2
if {[info exists env(XPIAN_TAG)]} {set tag $env(XPIAN_TAG)}
set out build/server/complete_soc_sm40_$tag
set report reports/server/complete_soc_sm40_$tag
file mkdir $out $report
define_design_lib WORK -path $out/work
if {$corner eq "ss"} {
    set cell_name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db
    set ram_corner ss_0p99v_0p99v_125c
} else {
    set cell_name scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db
    set ram_corner tt_1p10v_1p10v_25c
}
set cell_library [exec find build/server/technology -name $cell_name]
set ram_libraries [list build/server/technology/ram_db/RAMSP1024X16_${ram_corner}.db build/server/technology/ram_db/RAMSP128X16_${ram_corner}.db]
set ram_libraries [concat $ram_libraries [glob build/server/technology/platform_ram_db/*.db]]
set_app_var target_library [list $cell_library]
set_app_var synthetic_library dw_foundation.sldb
set_app_var link_library [concat * $target_library $ram_libraries dw_foundation.sldb]
set upstream build/server/official_2025/e203_hbirdv2-master/rtl/e203
set hdlin_include_dirs [list build/optimization/rtl_sources/ffn_r4f2_q8/encoder rtl/public_encoder build/optimization/complete_soc/ffn_r4f2_q8 $upstream/core $upstream/perips $upstream/perips/apb_i2c]
set_app_var search_path [concat $search_path $hdlin_include_dirs]
set_svf $out/design.svf
saif_map -start
set stream [open build/optimization/complete_soc/ffn_r4f2_q8/synthesis_files.f r]
set sources [split [string trim [read $stream]] "
"]
close $stream
if {[info exists env(XPIAN_DRC_FROM)]} {
    read_ddc $env(XPIAN_DRC_FROM)
    current_design kwt_complete_soc
    link
} else {
    analyze -format sverilog $sources
    elaborate kwt_complete_soc
    current_design kwt_complete_soc
    link
    uniquify
}
source constraints/complete_soc.sdc
if {[info exists env(XPIAN_MAX_CAP_PF)]} {
    set_max_capacitance $env(XPIAN_MAX_CAP_PF) [current_design]
}
if {[info exists env(XPIAN_INTERNAL_MAX_DELAY_NS)]} {
    set_max_delay $env(XPIAN_INTERNAL_MAX_DELAY_NS) -from [get_clocks clk] -to [get_clocks clk]
    puts "XPIAN_IMPLEMENTATION_MAX_DELAY_NS=$env(XPIAN_INTERNAL_MAX_DELAY_NS)"
}
if {[info exists env(XPIAN_SRAM_MIN_DELAY_NS)]} {
    set memory_inputs {}
    foreach_in_collection pin [get_pins -of_objects [get_cells -hierarchical -filter "ref_name =~ RAMSP*"]] {
        if {[regexp {/(A|D|WEN)(\[[0-9]+\])?$|/(CEN|GWEN)$} [get_object_name $pin]]} {
            lappend memory_inputs [get_object_name $pin]
        }
    }
    set_min_delay $env(XPIAN_SRAM_MIN_DELAY_NS) -from [get_clocks clk] -to [get_pins $memory_inputs]
    puts "XPIAN_SRAM_IMPLEMENTATION_MIN_DELAY_NS=$env(XPIAN_SRAM_MIN_DELAY_NS)"
}
set_fix_hold [get_clocks clk]
set_dont_touch [get_cells -hierarchical -filter "ref_name =~ RAMSP*"]
redirect $report/check_design.rpt {check_design}
redirect $report/libraries.rpt {
    foreach_in_collection library [get_libs *] {report_lib [get_object_name $library]}
}
if {[info exists env(XPIAN_RESIZE_SCRIPT)]} {
    source $env(XPIAN_RESIZE_SCRIPT)
} elseif {[info exists env(XPIAN_RESIZE_CELLS)]} {
    foreach cell $env(XPIAN_RESIZE_CELLS) {
        size_cell [get_cells $cell] [get_lib_cells */$env(XPIAN_RESIZE_TO)]
    }
} elseif {[info exists env(XPIAN_DRC_FROM)]} {
    compile -only_design_rule
} else {
    compile_ultra -no_autoungroup
}
change_names -rules verilog -hierarchy
redirect $report/area.rpt {report_area -hierarchy}
redirect $report/timing.rpt {report_timing -max_paths 10 -significant_digits 6 -transition_time -capacitance -nets}
redirect $report/qor.rpt {report_qor}
redirect $report/constraints.rpt {report_constraint -all_violators -significant_digits 6}
redirect $report/check_timing.rpt {check_timing}
redirect $report/resources.rpt {report_resources -hierarchy}
redirect $report/macros.rpt {report_cell [get_cells -hierarchical -filter "ref_name =~ RAMSP*"]}
source build/optimization/complete_soc/ffn_r4f2_q8/eda/area.tcl
write -format ddc -hierarchy -output $out/design.ddc
write -format verilog -hierarchy -output $out/netlist.v
write_sdc $out/design.sdc
write_sdf $out/design.sdf
if {[info exists env(XPIAN_SAIF)]} {
saif_map -create_map -input $env(XPIAN_SAIF) -source_instance complete_soc_tb/dut
saif_map -type ptpx -write_map $out/saif_map.tcl
}
set_svf -off
puts "XPIAN_SM40_SYNTH_DONE corner=$corner"
exit
