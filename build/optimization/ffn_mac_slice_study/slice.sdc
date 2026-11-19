create_clock -name clk -period 6.666666 [get_ports clk]
set_clock_transition 0.1 [all_clocks]
set data_inputs [remove_from_collection [all_inputs] [get_ports clk]]
set_input_transition 0.1 $data_inputs
set_input_delay -clock clk -max 0.7 $data_inputs
set_input_delay -clock clk -min 0.7 $data_inputs
set_output_delay -clock clk 0 [all_outputs]
set_load 0.002856 [all_outputs]
set_case_analysis 0 [get_ports clock_test_enable]
set_operating_conditions -analysis_type on_chip_variation ss_v0p99_125c
