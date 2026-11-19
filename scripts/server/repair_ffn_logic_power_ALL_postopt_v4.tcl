# Size only the two shared drivers on all five remaining negative setup paths.
set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
foreach {leaf old new} {U973 NAND2CV0_12TR40 NAND2V4_12TR40 U4350 CLKBUFV2_12TR40 CLKBUFV4_12TR40} {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual ALL v3 broadcast driver $leaf"}
    size_cell $cell [get_lib_cells */$new]
    puts "XPIAN_LP_ALL_POSTOPT_V4_SIZE $prefix/$leaf $old -> [get_attribute $cell ref_name]"
}
