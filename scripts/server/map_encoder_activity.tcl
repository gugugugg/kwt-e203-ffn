set tag $env(XPIAN_TAG)
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set_app_var target_library [list $cell_library]
set_app_var link_library [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_ss_0p99v_0p99v_125c.db build/server/technology/ram_db/RAMSP128X16_ss_0p99v_0p99v_125c.db]
saif_map -start
read_ddc build/server/encoder_sm40_$tag/design.ddc
current_design kwt_encoder_accelerator
link
saif_map -create_map -input reports/public_encoder/activity_00.saif -source_instance server_encoder_tb/dut/peripherals/accelerator
saif_map -type ptpx -write_map build/server/encoder_sm40_$tag/saif_map.tcl
puts "XPIAN_SAIF_MAP_RECOVERED"
exit
