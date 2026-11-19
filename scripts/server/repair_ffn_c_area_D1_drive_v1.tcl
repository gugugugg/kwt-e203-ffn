# Actual violated path cells only; same literal factory function.
set targets {
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3614 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U6422 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1000 NAND2V2_12TR40 NAND2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U603 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3244 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U605 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U595 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U217 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3311 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2162 NAND2CV1_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3582 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U219 CLKINV4_12TR40 CLKINV12_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U7644 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U997 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3064 NAND2CV1_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U432 CLKBUFV6_12TR40 CLKBUFV12_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U718 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U522 NAND2V2_12TR40 NAND2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U456 NAND2V2_12TR40 NAND2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U411 NAND2V2_12TR40 NAND2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U476 NAND2V2_12TR40 NAND2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U16469 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U497 NAND2V2_12TR40 NAND2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U29 NAND2V2_12TR40 NAND2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U13452 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U25414 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1077 NAND2CV0_12TR40 NAND2CV4_12TR40
}
set delta 0.0
foreach {path old new} $targets {
    set cell [get_cells $path]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual own checkpoint driver $path"}
    set delta [expr {$delta+[get_attribute [get_lib_cells */$new] area]-[get_attribute [get_lib_cells */$old] area]}]
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_C_AREA_SAME_FUNCTION_DRIVE $path $old -> $new"
}
puts "XPIAN_C_AREA_SAME_FUNCTION_DRIVE_DONE area_delta_um2=$delta"
