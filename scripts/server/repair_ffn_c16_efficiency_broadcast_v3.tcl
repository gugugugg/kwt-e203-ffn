# W own 8 failing setup paths: same-function broadcast drive resizing.
set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
set targets {
    U2379 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    U568 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    U573 BUFV2RQ_12TR40 BUFV8RQ_12TR40
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
puts "XPIAN_W_BROADCAST_REPAIR_DONE cells=3 area_delta_um2=$delta"
