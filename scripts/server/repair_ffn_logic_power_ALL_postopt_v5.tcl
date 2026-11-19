# Size only the shared buffer on the two remaining negative setup paths.
set name soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U4690
set cell [get_cells $name]
if {[get_attribute $cell ref_name] ne "BUFV2RQ_12TR40"} {error "Read actual ALL v4 buffer"}
size_cell $cell [get_lib_cells */BUFV4RQ_12TR40]
puts "XPIAN_LP_ALL_POSTOPT_V5_SIZE $name BUFV2RQ_12TR40 -> [get_attribute $cell ref_name]"
