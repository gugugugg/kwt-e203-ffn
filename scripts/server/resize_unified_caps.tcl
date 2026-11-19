foreach cell {
    peripherals/u_perips_apb_spi1/u_axiregs/U97
    peripherals/u_perips_apb_spi2/u_axiregs/U6
} {size_cell [get_cells $cell] [get_lib_cells */NOR4CV4_12TR40]}
foreach cell {
    u_cpu/u_e203_cpu/u_e203_core/u_e203_exu/u_e203_exu_csr/U119
    u_cpu/u_e203_cpu/u_e203_core/u_e203_exu/u_e203_exu_csr/U35
} {size_cell [get_cells $cell] [get_lib_cells */OAI21V3_12TR40]}
foreach cell {
    u_cpu/u_e203_srams/u_e203_dtcm_ram/u_sram_wrap_64KX32/memory/U43
    u_cpu/u_e203_srams/u_e203_dtcm_ram/u_sram_wrap_64KX32/memory/U46
} {size_cell [get_cells $cell] [get_lib_cells */NOR3CV2_12TR40]}
