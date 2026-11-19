# Actual violated path cells only; same literal factory function.
set targets {
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3424 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1095 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U939 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U881 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3876 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3572 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1066 NAND2V2_12TR40 NAND2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U768 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3422 CLKBUFV2_12TR40 CLKBUFV8_12TR40
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
