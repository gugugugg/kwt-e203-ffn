# Actual violated path cells only; same literal factory function.
set targets {
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U202 CLKINV2_12TR40 CLKINV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1260 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1147 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U5904 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U5905 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1201 NAND2CV1_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3241 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3242 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U215 INV2SR_12TR40 INV8SR_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U211 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2210 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2151 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1144 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1005 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3265 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1139 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U7660 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U7661 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U9538 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U9539 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1158 NAND2CV1_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1053 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3240 CLKBUFV2_12TR40 CLKBUFV8_12TR40
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
