set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
foreach {leaf old new} {
    U4531 OR2V0_12TR40 OR2V6_12TR40
    U5519 CLKINV2_12TR40 CLKINV12_12TR40
    U146 AND2V2_12TR40 AND2V8_12TR40
    U10020 CLKINV0_12TR40 CLKINV12_12TR40
    U4474 NOR2CV0_12TR40 NOR2CV4_12TR40
    U10047 NAND2BV2_12TR40 NAND2BV4_12TR40
    U10079 CLKINV0_12TR40 CLKINV12_12TR40
} {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Inspect actual failed-checkpoint driver $prefix/$leaf"}
    puts "XPIAN_LITERATURE_OBSERVED_RESIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_LITERATURE_TIMING_REPAIR_DONE=1"
