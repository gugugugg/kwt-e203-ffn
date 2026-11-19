set_host_options -max_cores 8
set cell_library [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set link_path [concat [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_ss_0p99v_0p99v_125c.db build/server/technology/ram_db/RAMSP128X16_ss_0p99v_0p99v_125c.db] [glob build/server/technology/platform_ram_db/*.db]]
read_verilog build/server/complete_soc_sm40_opt_ffn_lp_IR_broadcast_v3_final_ss_ema2/netlist.v
current_design kwt_complete_soc
link_design
set report reports/optimization/ffn_mac_slice_study/native/IR-reference
file mkdir $report
set stream [open $report/actual-cell-geometry.tsv w]
puts $stream "cell\tref\tarea"
foreach_in_collection cell [get_cells -hierarchical -filter "is_hierarchical == false"] {
 if {[string match "soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/*" [get_object_name $cell]]} {
  puts $stream "[get_object_name $cell]\t[get_attribute $cell ref_name]\t[get_attribute $cell area]"
 }
}
close $stream
puts "MAC_SLICE_IR_GEOMETRY_READONLY_DONE"
exit
