# W own 122 failing setup paths: same-function broadcast drive resizing.
set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
set targets {
    U2799 CLKINV4_12TR40 CLKINV8_12TR40
    U2815 NAND2V2_12TR40 NAND2V8_12TR40
    U2814 CLKINV2_12TR40 CLKINV4_12TR40
    U112 XNOR2V3_12TR40 XNOR2V6_12TR40
    U6637 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    U2933 XNOR2V3_12TR40 XNOR2V6_12TR40
    U772 CLKBUFV6_12TR40 CLKBUFV12_12TR40
    U5962 XNOR2V3_12TR40 XNOR2V6_12TR40
    U2585 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    U6048 XNOR2V3_12TR40 XNOR2V6_12TR40
    U775 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    U2545 XNOR2V3_12TR40 XNOR2V6_12TR40
    U2580 BUFV2RQ_12TR40 BUFV8RQ_12TR40
}
set delta 0.0
foreach {leaf old new} $targets {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Read own W broadcast driver $prefix/$leaf"}
    set old_area [get_attribute [get_lib_cells */$old] area]
    set new_area [get_attribute [get_lib_cells */$new] area]
    set delta [expr {$delta+$new_area-$old_area}]
    puts "XPIAN_W_BROADCAST_SIZE $prefix/$leaf $old -> $new area_delta=[expr {$new_area-$old_area}]"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_W_BROADCAST_REPAIR_DONE cells=13 area_delta_um2=$delta"
