set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
foreach {leaf old new} {
    U4955 BUFV4RQ_12TR40 BUFV16RQ_12TR40
    U92 NAND2CV0_12TR40 XNOR2V8_12TR40
    U482 NAND2CV0_12TR40 CLKBUFV12RQ_12TR40
    U2686 XNOR2V1_12TR40 XNOR2V3_12TR40
} {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Inspect actual failed-checkpoint driver $prefix/$leaf"}
    puts "XPIAN_LITERATURE_OBSERVED_RESIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_LITERATURE_TIMING_REPAIR_DONE=1"
