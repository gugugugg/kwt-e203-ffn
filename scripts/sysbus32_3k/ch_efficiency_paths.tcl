set paths {}
if {[string match *ffn_che_AG* $tag]} {
    set data_d [get_pins -hierarchical -filter {full_name =~ */core/*acc_?_reg*/D}]
    set data_q [get_pins -hierarchical -filter {full_name =~ */core/*acc_?_reg*/Q*}]
    set op_q [get_pins -hierarchical -filter {full_name =~ */core/operands_reg*/Q*}]
    set weights [get_pins -hierarchical -filter {full_name =~ */core/weight_columns*memory/Q*}]
    set quant_d [get_pins -hierarchical -filter {full_name =~ */core/quant_data_reg*/D}]
    set gate_e [get_pins -hierarchical -filter {full_name =~ */core/*accum_clocks*/cell_gate/E}]
    set tags_q [get_pins -hierarchical -filter {full_name =~ */core/tags_reg*/Q*}]
    lappend paths [list operand_to_acc $op_q $data_d] [list weight_to_acc $weights $data_d] \
        [list acc_feedback $data_q $data_d] [list acc_to_quant $data_q $quant_d] [list tag_to_icg $tags_q $gate_e]
} else {
    set macro_q [get_pins -hierarchical -filter {full_name =~ */input_codec/predictor_memory*memory/Q*}]
    set macro_d [get_pins -hierarchical -filter {full_name =~ */input_codec/predictor_memory*memory/D*}]
    set macro_a [get_pins -hierarchical -filter {full_name =~ */input_codec/predictor_memory*memory/A*}]
    set macro_e [get_pins -hierarchical -filter {full_name =~ */input_codec/predictor_memory*memory/CEN || full_name =~ */input_codec/predictor_memory*memory/GWEN}]
    set prev_q [get_pins -hierarchical -filter {full_name =~ */input_codec/prev_reg*/Q*}]
    set inner_q [get_pins -hierarchical -filter {full_name =~ */input_codec/inner_reg*/Q*}]
    set codec_d [get_pins -hierarchical -filter {full_name =~ */input_codec/assembled_reg*/D || full_name =~ */input_codec/fifo_reg*/D}]
    set enable_q [get_pins -hierarchical -filter {full_name =~ */input_codec/index_reg*/Q* || full_name =~ */input_codec/fill_reg*/Q*}]
    lappend paths [list macro_to_decode $macro_q $codec_d] [list prev_to_macro $prev_q $macro_d] \
        [list inner_to_macro $inner_q $macro_a] [list decode_to_macro_control $enable_q $macro_e]
}
redirect $report/ch_efficiency_paths.rpt {
    foreach pair $paths {
        lassign $pair label source target
        set ns [sizeof_collection $source]
        set nt [sizeof_collection $target]
        puts "CH_PATH $label $ns $nt"
        if {!$ns || !$nt} {error "Missing CH path endpoints: $label"}
        foreach delay {max min} {
            set timing [get_timing_paths -from $source -to $target -delay_type $delay -max_paths 3 -slack_lesser_than 1000000]
            if {![sizeof_collection $timing]} {error "Missing CH timing path: $label $delay"}
            report_timing -from $source -to $target -delay_type $delay -max_paths 3 -slack_lesser_than 1000000 -significant_digits 9
        }
    }
}
puts "CH_PATHS_DONE"
exit
