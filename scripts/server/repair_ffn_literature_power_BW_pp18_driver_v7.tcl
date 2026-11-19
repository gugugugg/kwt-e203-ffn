set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
foreach {leaf old new} {
    U12598 AOI222V2_12TR40 AOI222V8_12TR40
    U13562 AOI222V2_12TR40 AOI222V8_12TR40
    U14589 AOI22V0_12TR40 AOI22V4_12TR40
    U15044 AOI21V0_12TR40 AOI21V4_12TR40
    U16645 AOI222V2_12TR40 AOI222V8_12TR40
    U1719 AOI22V0_12TR40 AOI22V4_12TR40
    U3659 CLKINV4_12TR40 CLKINV12_12TR40
    U5081 AOI21V0_12TR40 AOI21V4_12TR40
    U5872 CLKINV2_12TR40 CLKINV8_12TR40
    U5873 CLKINV3_12TR40 CLKINV8_12TR40
    U6839 AO21V2_12TR40 AO21V8_12TR40
} {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Inspect actual PP18 v6 driver $prefix/$leaf"}
    puts "XPIAN_LITERATURE_OBSERVED_RESIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_LITERATURE_PP18_DRIVER_V7_DONE=1"
