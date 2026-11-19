set tag dual_v2_ss_ema2
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set_app_var target_library [list $cell_library]
set_app_var link_library [concat [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_ss_0p99v_0p99v_125c.db build/server/technology/ram_db/RAMSP128X16_ss_0p99v_0p99v_125c.db] [glob build/server/technology/platform_ram_db/*.db]]
read_ddc build/server/unified_platform_sm40_$tag/design.ddc
current_design kwt_encoder_platform
link
foreach path {
 peripherals/u_perips_apb_spi1/u_axiregs/U97
 peripherals/u_perips_apb_spi2/u_axiregs/U6
 u_cpu/u_e203_cpu/u_e203_core/u_e203_exu/u_e203_exu_csr/U119
 u_cpu/u_e203_cpu/u_e203_core/u_e203_exu/u_e203_exu_csr/U35
 u_cpu/u_e203_srams/u_e203_dtcm_ram/u_sram_wrap_64KX32/memory/U43
 u_cpu/u_e203_srams/u_e203_dtcm_ram/u_sram_wrap_64KX32/memory/U46
} {
    puts "DRIVER [file tail $path] [get_attribute [get_cells $path] ref_name]"
}
foreach pattern {NOR4CV* OAI21V* NOR3CV*} {
    puts "AVAILABLE $pattern [get_object_name [get_lib_cells */$pattern]]"
}
puts "BUFV1_INPUT_CAP_PF=[get_attribute [get_lib_pins */BUFV1_12TR40/I] capacitance]"
foreach path {peripherals/U14/Z peripherals/U15/Z peripherals/U16/Z} {
    puts "MINCAP_CONNECTION $path [get_object_name [all_connected [get_nets -of_objects [get_pins $path]]]]"
}
exit
