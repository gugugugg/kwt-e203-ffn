set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
foreach {leaf old new} {
    U147 BUFV2_12TR40 BUFV8_12TR40
    U3599 CLKXOR2V2_12TR40 CLKXOR2V8_12TR40
    U3601 CLKXOR2V2_12TR40 CLKXOR2V8_12TR40
    U391 BUFV2RQ_12TR40 BUFV12RQ_12TR40
    U393 CLKBUFV6_12TR40 CLKBUFV12_12TR40
    U462 XNOR2V0_12TR40 XNOR2V8_12TR40
    U786 XNOR2V1_12TR40 XNOR2V8_12TR40
    U847 CLKBUFV6_12TR40 CLKBUFV12_12TR40
} {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Inspect actual CROSS hold driver $prefix/$leaf"}
    puts "XPIAN_LITERATURE_OBSERVED_RESIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_LITERATURE_CROSS_BROADCAST_V2_DONE=1"
