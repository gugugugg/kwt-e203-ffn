# The two drivers common to this ALL checkpoint's reported setup failures.
set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
foreach {leaf old new} {
    U122 NAND2V2_12TR40 NAND2V8_12TR40
    U3704 CLKBUFV2_12TR40 CLKBUFV4_12TR40
} {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual ALL driver $prefix/$leaf"}
    puts "XPIAN_LP_ALL_TIMING_SIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_LP_ALL_TIMING_REPAIR_DONE cells=2"
compile -only_design_rule
compile -only_hold_time
