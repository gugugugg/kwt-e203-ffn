set tag $env(XPIAN_TAG)
set cell_library [exec find -L build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set_app_var target_library [list $cell_library]
set_app_var link_library [concat [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_ss_0p99v_0p99v_125c.db build/server/technology/ram_db/RAMSP128X16_ss_0p99v_0p99v_125c.db] [glob build/server/technology/platform_ram_db/*.db]]
saif_map -start
if {![file exists $env(XPIAN_SAIF)]} {error "Task SAIF does not exist: $env(XPIAN_SAIF)"}
read_ddc build/server/complete_soc_sm40_$tag/design.ddc
current_design kwt_complete_soc
link
saif_map -create_map -input $env(XPIAN_SAIF) -source_instance complete_soc_tb/dut
saif_map -type ptpx -write_map build/server/complete_soc_sm40_$tag/saif_map.tcl
puts "XPIAN_UNIFIED_SAIF_MAP_RECOVERED"
exit
