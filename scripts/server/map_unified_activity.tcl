set tag $env(XPIAN_TAG)
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set_app_var target_library [list $cell_library]
set_app_var link_library [concat [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_ss_0p99v_0p99v_125c.db build/server/technology/ram_db/RAMSP128X16_ss_0p99v_0p99v_125c.db] [glob build/server/technology/platform_ram_db/*.db]]
saif_map -start
if {![file exists $env(XPIAN_SAIF)]} {error "Task SAIF does not exist: $env(XPIAN_SAIF)"}
read_ddc build/server/unified_platform_sm40_$tag/design.ddc
current_design kwt_encoder_platform
link
saif_map -create_map -input $env(XPIAN_SAIF) -source_instance unified_cpu_tb/dut
saif_map -type ptpx -write_map build/server/unified_platform_sm40_$tag/saif_map.tcl
puts "XPIAN_UNIFIED_SAIF_MAP_RECOVERED"
exit
