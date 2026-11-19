set private_prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
set preserved_public_leaves 0
foreach_in_collection cell [get_cells -hierarchical -filter {is_hierarchical == false}] {
    if {![string match "$private_prefix/*" [get_object_name $cell]]} {
        set_dont_touch $cell
        incr preserved_public_leaves
    }
}
puts "XPIAN_LITERATURE_PUBLIC_LEAVES_PRESERVED=$preserved_public_leaves"
compile_ultra -incremental -no_autoungroup
puts "XPIAN_LITERATURE_BW_INCREMENTAL_TIMING_REPAIR_DONE=1"
