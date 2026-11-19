# Remaining v2 input-return broadcast branches only.
set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
switch -glob -- $env(XPIAN_TAG) {
    *ffn_lp_C4_* {set targets {U449 BUFV2RQ_12TR40 BUFV4RQ_12TR40}}
    *ffn_lp_IR_* {set targets {U1347 BUFV4RQ_12TR40 BUFV8RQ_12TR40}}
    *ffn_lp_DQ_* {set targets {U2188 BUFV2RQ_12TR40 BUFV4RQ_12TR40}}
    default {error "Read this round actual broadcast-repair tag"}
}
foreach {leaf old new} $targets {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual broadcast driver $prefix/$leaf"}
    puts "XPIAN_LP_BROADCAST_SIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_LP_BROADCAST_REPAIR_DONE cells=[expr {[llength $targets]/3}]"
