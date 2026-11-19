# These buffers are on the actual negative-slack input-return-to-MAC paths.
set prefix soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core
if {[string match *ffn_jp_HM2_* $env(XPIAN_TAG)]} {
    set targets {U1366 BUFV4RQ_12TR40 BUFV8RQ_12TR40 U370 BUFV2RQ_12TR40 BUFV4RQ_12TR40 U433 BUFV2RQ_12TR40 BUFV4RQ_12TR40 U2253 BUFV2RQ_12TR40 BUFV4RQ_12TR40 U379 BUFV2RQ_12TR40 BUFV4RQ_12TR40}
} else {
    set targets {U287 BUFV2RQ_12TR40 BUFV4RQ_12TR40 U3547 BUFV4RQ_12TR40 BUFV8RQ_12TR40 U192 BUFV2RQ_12TR40 BUFV4RQ_12TR40}
}
foreach {leaf old new} $targets {
    set cell [get_cells $prefix/$leaf]
    if {[get_attribute $cell ref_name] ne $old} {error "Read actual broadcast driver $prefix/$leaf"}
    puts "XPIAN_JP_BROADCAST_SIZE $prefix/$leaf $old -> $new"
    size_cell $cell [get_lib_cells */$new]
}
puts "XPIAN_JP_BROADCAST_REPAIR_DONE cells=[expr {[llength $targets]/3}]"
