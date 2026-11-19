create_clock -name hfref -period 6.666666 [get_ports hfextclk]
create_clock -name ls_clk -period 30517.578125 [get_ports lfextclk]
create_clock -name jtag_clk -period 100 [get_ports io_pads_jtag_TCK_i_ival]
create_clock -name clk -period 6.666666 [get_pins soc/u_e203_subsys_main/u_e203_subsys_hclkgen/hfclk]
set_ideal_network [get_pins soc/u_e203_subsys_main/u_e203_subsys_hclkgen/hfclk]
set_clock_transition 0.1 [all_clocks]
set_clock_groups -asynchronous -group [get_clocks {hfref clk}] -group [get_clocks ls_clk] -group [get_clocks jtag_clk]
set data_inputs [remove_from_collection [all_inputs] [get_ports {hfextclk lfextclk io_pads_jtag_TCK_i_ival}]]
set_input_transition 0.1 $data_inputs
set_input_delay -clock clk -max 0.7 $data_inputs
set_input_delay -clock clk -min 0.7 $data_inputs
set jtag_inputs [get_ports {io_pads_jtag_TMS_i_ival io_pads_jtag_TDI_i_ival io_pads_jtag_TRST_n_i_ival}]
set_input_delay -clock jtag_clk -max 0.7 $jtag_inputs
set_input_delay -clock jtag_clk -min 0.7 $jtag_inputs
set data_outputs [remove_from_collection [all_outputs] [get_ports system_clk]]
set_output_delay -clock clk 0 $data_outputs
set aon_outputs [get_ports {io_pads_aon*_o_*}]
set_output_delay -clock ls_clk 0 $aon_outputs
set jtag_outputs [get_ports {io_pads_jtag*_o_*}]
set_output_delay -clock jtag_clk 0 $jtag_outputs
set_load 0.002856 [all_outputs]
set_case_analysis 0 [get_ports {core_mhartid* test_mode test_iso_override io_pads_bootrom_n_i_ival}]
set_case_analysis 1 [get_ports {io_pads_dbgmode0_n_i_ival io_pads_dbgmode1_n_i_ival io_pads_dbgmode2_n_i_ival}]
# The supplied PLL model passes the reference clock through; task SAIF has pllbypass=1 throughout.
set_case_analysis 1 [get_pins soc/u_e203_subsys_main/u_e203_subsys_hclkgen/pllbypass]
