set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
foreach {leaf old new} {
    U279 CLKINV2_12TR40 CLKINV12_12TR40
    U9808 OR2V0_12TR40 OR2V6_12TR40
    U3852 AOI211V2_12TR40 AOI211V4_12TR40
    U9804 CLKINV2_12TR40 CLKINV12_12TR40
    U9803 NOR2CV1_12TR40 NOR2CV6_12TR40
} {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Inspect actual failed-checkpoint driver $prefix/$leaf"}
    puts "XPIAN_LITERATURE_OBSERVED_RESIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_LITERATURE_TIMING_REPAIR_DONE=1"
