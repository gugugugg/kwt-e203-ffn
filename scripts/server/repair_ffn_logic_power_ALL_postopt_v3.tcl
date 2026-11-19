# Preserve the completed hold optimization; apply this one same-function ECO afterward.
set name soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/U122
set cell [get_cells $name]
if {[get_attribute $cell ref_name] ne "NAND2V2_12TR40"} {error "Read this ALL checkpoint's actual NAND driver"}
size_cell $cell [get_lib_cells */NAND2V8_12TR40]
puts "XPIAN_LP_ALL_POSTOPT_SIZE $name NAND2V2_12TR40 -> [get_attribute $cell ref_name]"
