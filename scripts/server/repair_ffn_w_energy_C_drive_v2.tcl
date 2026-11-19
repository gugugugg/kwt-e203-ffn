# C actual reset-recovery and MAC broadcast paths: same-function drive sizing only.
set targets {
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U1996 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U832 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U948 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3156 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U782 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U5855 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U874 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U718 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3197 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U869 NAND2CV0_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U715 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U817 CLKBUFV2_12TR40 CLKBUFV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U175 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U3387 BUFV2RQ_12TR40 BUFV8RQ_12TR40
}
set delta 0.0
foreach {path old new} $targets {
    set cell [get_cells $path]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual C hold driver $path"}
    set old_area [get_attribute [get_lib_cells */$old] area]
    set new_area [get_attribute [get_lib_cells */$new] area]
    set delta [expr {$delta+$new_area-$old_area}]
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_WEN_C_DRIVE $path $old -> $new"
}
puts "XPIAN_WEN_C_DRIVE_DONE cells=14 area_delta_um2=$delta"
