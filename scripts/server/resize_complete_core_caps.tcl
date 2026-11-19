set core soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
size_cell [get_cells $core/U24756] [get_lib_cells */NOR2CV6_12TR40]
foreach cell [list $core/divider/U27 $core/U6273 $core/U24640] {
    size_cell [get_cells $cell] [get_lib_cells */CLKINV1_12TR40]
}
