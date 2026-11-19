# Replace the one adapter primitive left unmapped inside the frozen SR core.
set core soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
set_dont_touch [get_cells $core] false
current_instance $core
set old [get_cells I_0]
if {[get_attribute $old ref_name] ne "GTECH_NOT"} {error "Unexpected old index adapter"}
set input_net [get_nets -of_objects [get_pins I_0/A]]
set output_net [get_nets -of_objects [get_pins I_0/Z]]
set_dont_touch $old false
remove_cell $old
create_cell I_0 [get_lib_cells */CLKINV2_12TR40]
connect_net $input_net [get_pins I_0/I]
connect_net $output_net [get_pins I_0/ZN]
puts "XPIAN_INDEX_INVERTER_MAPPED [get_object_name $input_net] [get_object_name $output_net]"
current_instance
set_dont_touch [get_cells $core]
