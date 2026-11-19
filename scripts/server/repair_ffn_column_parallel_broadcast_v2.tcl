# Six remaining broadcast drivers on the four v1 failing setup paths.
set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
set targets {
    U3244 XNOR2V3_12TR40 XNOR2V6_12TR40
    U3260 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    U3243 XNOR2V3_12TR40 XNOR2V6_12TR40
    U3245 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    U3229 XNOR2V3_12TR40 XNOR2V6_12TR40
    U3232 BUFV4RQ_12TR40 BUFV8RQ_12TR40
}
set delta 0.0
foreach {leaf old new} $targets {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual C16 broadcast driver $prefix/$leaf"}
    set old_area [get_attribute [get_lib_cells */$old] area]
    set new_area [get_attribute [get_lib_cells */$new] area]
    set delta [expr {$delta+$new_area-$old_area}]
    puts "XPIAN_C16_BROADCAST_SIZE $prefix/$leaf $old -> $new area_delta=[expr {$new_area-$old_area}]"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_C16_BROADCAST_REPAIR_DONE cells=6 area_delta_um2=$delta"
