# W own 67 failing setup paths: same-function broadcast drive resizing.
set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
set targets {
    U105 INV2SR_12TR40 INV4SR_12TR40
    U5356 XNOR2V3_12TR40 XNOR2V6_12TR40
    U5357 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    U176 CLKINV2_12TR40 CLKINV4_12TR40
    U177 XNOR2V3_12TR40 XNOR2V6_12TR40
    U679 CLKBUFV6_12TR40 CLKBUFV12_12TR40
    U2890 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    U2914 CLKINV0_12TR40 CLKINV4_12TR40
    U730 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    U96 INV2SR_12TR40 INV4SR_12TR40
    U95 XNOR2V3_12TR40 XNOR2V6_12TR40
    U6010 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    U182 XNOR2V3_12TR40 XNOR2V6_12TR40
    U7856 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    U7891 XNOR2V3_12TR40 XNOR2V6_12TR40
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
puts "XPIAN_W_BROADCAST_REPAIR_DONE cells=15 area_delta_um2=$delta"
