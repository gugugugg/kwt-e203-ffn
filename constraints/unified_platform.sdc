source constraints/public_encoder_platform.sdc
# BUFV1_12TR40/I capacitance in the supplied SS library: 0.000714 pF.
set unified_reference_capacitance_pf 0.000714
set unified_output_capacitance_pf [expr {4.0*$unified_reference_capacitance_pf}]
set_load $unified_output_capacitance_pf [all_outputs]
puts "XPIAN_UNIFIED_OUTPUT_LOAD_PF=$unified_output_capacitance_pf"
