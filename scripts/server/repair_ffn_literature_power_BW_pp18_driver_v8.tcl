set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
foreach {leaf old new} {
    U16364 AOI211V0_12TR40 AOI211V4_12TR40
    U4302 CLKINV0_12TR40 CLKINV12_12TR40
    U4621 NOR2CV4_12TR40 NOR2CV12_12TR40
    U698 OAI21V0_12TR40 OAI21V4_12TR40
} {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Inspect actual PP18 v7 driver $prefix/$leaf"}
    puts "XPIAN_LITERATURE_OBSERVED_RESIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_LITERATURE_PP18_DRIVER_V8_DONE=1"
