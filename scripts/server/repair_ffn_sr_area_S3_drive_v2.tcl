# Actual violated path cells only; same literal factory function.
set targets {
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1647 CLKINV4_12TR40 CLKINV12_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U7715 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U7716 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U910 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U911 BUFV2RQ_12TR40 BUFV8RQ_12TR40
}
set delta 0.0
foreach {path old new} $targets {
    set cell [get_cells $path]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual own checkpoint driver $path"}
    set delta [expr {$delta+[get_attribute [get_lib_cells */$new] area]-[get_attribute [get_lib_cells */$old] area]}]
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_SR_AREA_SAME_FUNCTION_DRIVE $path $old -> $new"
}
puts "XPIAN_SR_AREA_SAME_FUNCTION_DRIVE_DONE area_delta_um2=$delta"
