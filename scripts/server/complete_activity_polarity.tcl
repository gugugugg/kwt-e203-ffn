# NOR2BV0 in the mapped shared controller accepts ready & ~cpu_cmd_valid_BAR.
# These aliases carry that same complemented signal through the native sysmem path.
set_rtl_to_gate_name -rtl {sysmem_icb_cmd_valid} -gate {sysmem_icb_cmd_valid} -inverted
set_rtl_to_gate_name -rtl {soc/sysmem_icb_cmd_valid} -gate {soc/sysmem_icb_cmd_valid_BAR} -inverted
set_rtl_to_gate_name -rtl {shared_memory/cpu_cmd_valid} -gate {shared_memory/cpu_cmd_valid_BAR} -inverted
set_rtl_to_gate_name -rtl {soc/u_e203_subsys_main/sysmem_icb_cmd_valid} -gate {soc/u_e203_subsys_main/sysmem_icb_cmd_valid_BAR} -inverted
set_rtl_to_gate_name -rtl {soc/u_e203_subsys_main/u_e203_subsys_mems/sysmem_icb_cmd_valid} -gate {soc/u_e203_subsys_main/u_e203_subsys_mems/sysmem_icb_cmd_valid_BAR} -inverted
