# SL actual MAC broadcast paths: same-function drive sizing only.
set targets {
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U872 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U5997 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U629 NAND2CV1_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U513 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2787 CLKINV4_12TR40 CLKINV12_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2802 NAND2V2_12TR40 NAND2V12_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2801 CLKINV2_12TR40 CLKINV12_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U167 CLKINV2_12TR40 CLKINV8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U168 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U675 CLKBUFV6_12TR40 CLKBUFV12_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2878 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U516 BUFV2RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2029 XNOR2V3_12TR40 XNOR2V8_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U7878 BUFV4RQ_12TR40 BUFV8RQ_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U2019 NAND2CV2_12TR40 NAND2CV4_12TR40
    soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U533 CLKBUFV2_12TR40 CLKBUFV8_12TR40
}
set delta 0.0
foreach {path old new} $targets {
    set cell [get_cells $path]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual SL hold driver $path"}
    set old_area [get_attribute [get_lib_cells */$old] area]
    set new_area [get_attribute [get_lib_cells */$new] area]
    set delta [expr {$delta+$new_area-$old_area}]
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_WEN_SL_DRIVE $path $old -> $new"
}
puts "XPIAN_WEN_SL_DRIVE_DONE cells=16 area_delta_um2=$delta"
