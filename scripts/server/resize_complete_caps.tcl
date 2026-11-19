set core soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
size_cell [get_cells $core/U24756] [get_lib_cells */NOR2CV6_12TR40]
foreach cell [list $core/divider/U27 $core/U6273 $core/U24640] {
    size_cell [get_cells $cell] [get_lib_cells */CLKINV1_12TR40]
}
set memory soc/u_e203_subsys_main/u_e203_cpu_top/u_e203_srams/u_e203_dtcm_ram/u_sram_wrap_64KX32/memory
foreach cell [list $memory/U113 $memory/U116] {
    size_cell [get_cells $cell] [get_lib_cells */NOR3CV2_12TR40]
}
redirect $report/mapping_polarity.rpt {
    saif_map -report -instances [get_cells shared_memory] -columns {type object_names orig_names extended_orig_names attributes}
}
