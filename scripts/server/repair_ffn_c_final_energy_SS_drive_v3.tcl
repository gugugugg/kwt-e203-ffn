# Actual violated path cells only; same literal factory function.
set targets {
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U285 CLKINV2_12TR40 CLKINV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U7562 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U7563 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1708 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U10148 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2467 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1102 NAND2CV1_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U884 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U882 BUFV2RQ_12TR40 BUFV8RQ_12TR40
}
set delta 0.0
foreach {path old new} $targets {
    set cell [get_cells $path]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual own checkpoint driver $path"}
    set delta [expr {$delta+[get_attribute [get_lib_cells */$new] area]-[get_attribute [get_lib_cells */$old] area]}]
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_CFE_SAME_FUNCTION_DRIVE $path $old -> $new"
}
puts "XPIAN_CFE_SAME_FUNCTION_DRIVE_DONE area_delta_um2=$delta"
