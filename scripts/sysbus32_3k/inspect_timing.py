"""Report mapped paths specific to the single-bus two-page design."""
import os

from native_soc import ROOT, REPORT, SOC, flow

PATHS = r'''
set cmd_q [get_pins -hierarchical -quiet -filter {full_name =~ */u_sirv_gnrl_cmd_fifo/*/qout*}]
set shared [get_pins -hierarchical -quiet -filter {full_name =~ shared_memory/memory/*/A* || full_name =~ shared_memory/memory/*/D* || full_name =~ shared_memory/memory/*/CEN}]
set shared_q [get_pins -hierarchical -quiet -filter {full_name =~ shared_memory/memory/*/Q*}]
set rsp_d [get_pins -hierarchical -quiet -filter {full_name =~ */u_sirv_gnrl_rsp_fifo/*/*/D}]
set slot_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/out_word_reg*/Q* || full_name =~ */core/out_addr_reg*/Q*}]
set result_rd [get_pins -hierarchical -quiet -filter {full_name =~ */core/result_banks*memory/Q*}]
set slot_d [get_pins -hierarchical -quiet -filter {full_name =~ */core/out_word_reg*/D}]
set prefix_q [get_pins -hierarchical -quiet -filter {full_name =~ */shared_masters/parameter_committed_reg*/Q* || full_name =~ */shared_masters/input_committed_reg*/Q*}]
set bus_out [get_pins -hierarchical -quiet -filter {full_name =~ */u_sirv_gnrl_cmd_fifo/*/*/D}]
set decoder_paths {}
foreach codec {input_codec parameter_codec} {
    set codec_q [get_pins -hierarchical -quiet -filter "full_name =~ */$codec/bits_reg*/Q*"]
    set codec_d [get_pins -hierarchical -quiet -filter "full_name =~ */$codec/fifo_reg*/D || full_name =~ */$codec/assembled_reg*/D"]
    set reservoir_d [get_pins -hierarchical -quiet -filter "full_name =~ */$codec/bits_reg*/D"]
    lappend decoder_paths [list ${codec}_decode $codec_q $codec_d] [list ${codec}_shift $codec_q $reservoir_d]
}
set predictor [get_pins -hierarchical -quiet -filter {full_name =~ */input_codec/row7_reg*/Q* || full_name =~ */input_codec/prev_reg*/Q*}]
set predicted [get_pins -hierarchical -quiet -filter {full_name =~ */input_codec/fifo_reg*/D || full_name =~ */input_codec/assembled_reg*/D}]
if {[sizeof_collection $predictor] && [sizeof_collection $predicted]} {
    lappend decoder_paths [list input_predictor $predictor $predicted]
}
redirect $report/sysbus3k_paths.rpt {
    foreach pair [concat [list [list result_to_hold $result_rd $slot_d] [list write_hold_to_bus $slot_q $bus_out] [list committed_prefix_to_bus $prefix_q $bus_out] [list shared_return_to_bus $shared_q $rsp_d] [list bus_to_shared $cmd_q $shared]] $decoder_paths] {
        lassign $pair label from_pins to_pins
        puts "SYSBUS3K_PATH $label [sizeof_collection $from_pins] [sizeof_collection $to_pins]"
        if {[sizeof_collection $from_pins] && [sizeof_collection $to_pins]} {
            report_timing -from $from_pins -to $to_pins -delay_type max -max_paths 3 -slack_lesser_than 1000000 -significant_digits 9
            report_timing -from $from_pins -to $to_pins -delay_type min -max_paths 3 -slack_lesser_than 1000000 -significant_digits 9
        }
    }
}
puts "SYSBUS3K_PATH_REPORT_DONE"
exit
'''


if __name__ == '__main__':
    tcl = REPORT / 'sysbus3k_paths.tcl'
    base = (SOC / 'eda/time.tcl').read_text(encoding='utf-8').split('if {$assessment_setup < 0', 1)[0]
    tcl.write_text(base + PATHS, encoding='utf-8')
    env = dict(os.environ, XPIAN_TAG=flow.flow.tag('final'), XPIAN_CORNER='ss')
    flow.flow.run('pt_shell', tcl, REPORT / 'sysbus3k_paths.log', env)
