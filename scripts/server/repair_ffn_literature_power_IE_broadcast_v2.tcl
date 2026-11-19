# Exact sign/decode broadcast drivers reported by IE's failed hold checkpoint.
set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
foreach {leaf old new} {
    U3004 CLKINV4_12TR40 CLKINV12_12TR40
    U2664 XNOR2V1_12TR40 XNOR2V3_12TR40
    U63 CLKINV4_12TR40 CLKINV12_12TR40
    U385 BUFV2RQ_12TR40 BUFV4RQ_12TR40
    U1698 XNOR2V0_12TR40 XNOR2V3_12TR40
    U4301 CLKINV2_12TR40 CLKINV12_12TR40
} {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Inspect actual IE failed-checkpoint driver $prefix/$leaf"}
    puts "XPIAN_LIT_IE_BROADCAST_RESIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_LIT_IE_BROADCAST_REPAIR_DONE=1"
