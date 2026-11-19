# Called only after the candidate's normal update_power.
proc ap_evidence_attribute_inventory {report_dir} {
    global ap_evidence_available
    array unset ap_evidence_available
    foreach kind {cell pin net} {
        set path $report_dir/area_power_attributes_${kind}.rpt
        redirect $path {list_attributes -application -class $kind}
        set stream [open $path r]
        foreach line [split [read $stream] "\n"] {
            if {[regexp {^\s*([A-Za-z_][A-Za-z0-9_]*)\s+} $line unused name]} {
                set ap_evidence_available($kind,$name) 1
            }
        }
        close $stream
    }
}

proc ap_evidence_attr {object kind attribute} {
    global ap_evidence_available
    if {![info exists ap_evidence_available($kind,$attribute)]} {return NA}
    if {[catch {get_attribute $object $attribute} value] || $value eq ""} {return NA}
    return $value
}

proc ap_evidence_json_string {value} {
    return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $value]\""
}

proc ap_evidence_pin_segments {pin direction} {
    if {$direction eq "internal"} {return ""}
    set attached [get_attribute $pin net]
    if {[sizeof_collection $attached] == 0} {return ""}
    return [get_nets -segments -of_objects $pin]
}

proc ap_export_evidence {report_dir} {
    global activity tag
    ap_evidence_attribute_inventory $report_dir
    set macros [open $report_dir/area_power_macros.tsv w]
    set pins [open $report_dir/area_power_pins.tsv w]
    set nets [open $report_dir/area_power_nets.tsv w]
    set drivers [open $report_dir/area_power_drivers.tsv w]
    set connections [open $report_dir/area_power_connections.tsv w]
    set net_drivers [open $report_dir/area_power_net_drivers.tsv w]
    set unconnected [open $report_dir/area_power_unconnected_pins.tsv w]
    puts $macros "role\tcell\tref_name\tarea_um2\tinternal_w\tswitching_w\tleakage_w\ttotal_w"
    puts $pins "role\tpin\tcell\tref_name\tdirection\trise_transition_max\tfall_transition_max"
    puts $nets "net\tstatic_probability_native\ttoggle_rate_native\tload_pins\ttotal_capacitance"
    puts $drivers "cell\tref_name\tarea_um2\tinternal_w\tswitching_w\tleakage_w\ttotal_w"
    puts $connections "pin\tsegment"
    puts $net_drivers "segment\tdriver_pin\tdriver_cell\tref_name"
    puts $unconnected "role\tpin\tdirection\tconstant_value_native\treason"

    set cells [get_cells -hierarchical * -filter {is_hierarchical == false}]
    set pin_queue {}
    array set pin_roles {}
    array set pin_seen {}
    array set net_seen {}
    array set driver_seen {}
    set weight_count 0
    set input_count 0
    foreach_in_collection cell $cells {
        set name [get_object_name $cell]
        set ref [get_attribute $cell ref_name]
        set role ""
        if {$ref eq "RAMSP1024X16" && [string match *accelerator*core*parameter_banks*weights* $name]} {
            set role weight
            incr weight_count
        } elseif {$ref eq "RAMSP128X16" && [string match *accelerator*core*ap_input_rows*memory* $name]} {
            set role input
            incr input_count
        } elseif {[string match CLKLANA* $ref] && [string match *accelerator*core*parameter_banks*gated_gate* $name]} {
            set role weight_clock_gate
        } elseif {[string match CLKLANA* $ref] && [string match *accelerator*core*ap_input_rows*gate* $name]} {
            set role input_clock_gate
        }
        if {$role eq ""} {continue}
        if {$role eq "weight" || $role eq "input"} {
            puts $macros [join [list $role $name $ref [ap_evidence_attr $cell cell area] \
                [ap_evidence_attr $cell cell internal_power] [ap_evidence_attr $cell cell switching_power] \
                [ap_evidence_attr $cell cell leakage_power] [ap_evidence_attr $cell cell total_power]] "\t"]
        }
        foreach_in_collection pin [get_pins -of_objects $cell] {
            set pin_name [get_object_name $pin]
            set leaf [lindex [split $pin_name /] end]
            if {$role eq "weight" || $role eq "input"} {
                if {![regexp {^(CLK|CEN|GWEN|WEN(\[[0-9]+\])?|A\[[0-9]+\]|D\[[0-9]+\]|Q\[[0-9]+\])$} $leaf]} {continue}
            }
            lappend pin_queue $pin
            set pin_roles($pin_name) $role
        }
    }

    for {set index 0} {$index < [llength $pin_queue]} {incr index} {
        set pin [lindex $pin_queue $index]
        set pin_name [get_object_name $pin]
        if {[info exists pin_seen($pin_name)]} {continue}
        set pin_seen($pin_name) 1
        set role $pin_roles($pin_name)
        set cell [get_cells -of_objects $pin]
        set direction [get_attribute $pin direction]
        puts $pins [join [list $role $pin_name [get_object_name $cell] [get_attribute $cell ref_name] \
            $direction [ap_evidence_attr $pin pin actual_rise_transition_max] \
            [ap_evidence_attr $pin pin actual_fall_transition_max]] "\t"]
        set segments [ap_evidence_pin_segments $pin $direction]
        if {[sizeof_collection $segments] == 0} {
            if {$direction eq "internal"} {
                puts $unconnected [join [list $role $pin_name $direction NA internal_library_pin] "\t"]
            } else {
                puts $unconnected [join [list $role $pin_name $direction \
                    [ap_evidence_attr $pin pin constant_value] no_connected_net] "\t"]
            }
            continue
        }
        foreach_in_collection net $segments {
            set net_name [get_object_name $net]
            puts $connections [join [list $pin_name $net_name] "\t"]
            if {[info exists net_seen($net_name)]} {continue}
            set net_seen($net_name) 1
            set connected [all_connected -leaf $net]
            set receivers [filter_collection $connected {object_class == pin && direction == in}]
            puts $nets [join [list $net_name [get_switching_activity -static_probability $net] \
                [get_switching_activity -toggle_rate $net] [sizeof_collection $receivers] \
                [ap_evidence_attr $net net total_capacitance]] "\t"]
            set source_pins [filter_collection $connected {object_class == pin && direction == out}]
            foreach_in_collection source_port [filter_collection $connected {object_class == port && direction == in}] {
                puts $net_drivers [join [list $net_name [get_object_name $source_port] "" PORT] "\t"]
            }
            foreach_in_collection source_pin $source_pins {
                set source_cell [get_cells -of_objects $source_pin]
                set source_name [get_object_name $source_cell]
                puts $net_drivers [join [list $net_name [get_object_name $source_pin] $source_name \
                    [get_attribute $source_cell ref_name]] "\t"]
                if {![info exists driver_seen($source_name)]} {
                    set driver_seen($source_name) 1
                    puts $drivers [join [list $source_name [get_attribute $source_cell ref_name] \
                        [ap_evidence_attr $source_cell cell area] [ap_evidence_attr $source_cell cell internal_power] \
                        [ap_evidence_attr $source_cell cell switching_power] [ap_evidence_attr $source_cell cell leakage_power] \
                        [ap_evidence_attr $source_cell cell total_power]] "\t"]
                }
                if {$role ne "driver_input"} {
                    foreach_in_collection source_input [get_pins -of_objects $source_cell -filter {direction == in}] {
                        set input_name [get_object_name $source_input]
                        if {![info exists pin_roles($input_name)]} {
                            set pin_roles($input_name) driver_input
                            lappend pin_queue $source_input
                        }
                    }
                }
            }
        }
    }
    foreach stream [list $macros $pins $nets $drivers $connections $net_drivers $unconnected] {close $stream}

    set context [open $report_dir/area_power_context.json w]
    set source_activity ""
    set source_map ""
    set source_tag ""
    if {[info exists activity]} {set source_activity $activity}
    if {[info exists tag]} {
        set source_tag $tag
        set source_map build/server/complete_soc_sm40_$tag/saif_map.tcl
    }
    puts $context [format {{"unit":"W","stage":"after_candidate_update_power","export_calls_update_power":false,"weight_macros":%d,"input_macros":%d,"tag":%s,"activity":%s,"saif_map":%s,"strip_path":"complete_soc_tb/dut","driver_cells_deduplicated":true}} \
        $weight_count $input_count [ap_evidence_json_string $source_tag] \
        [ap_evidence_json_string $source_activity] [ap_evidence_json_string $source_map]]
    close $context
    set components [open $report_dir/area_power_internal_components.json w]
    puts $components {{"status":"not_separated","native_internal_w":"area_power_macros.tsv","clock_address_contributions":null,"reason":"Only native cell internal_power totals are exported; no unverified conditional-arc contribution API is invoked."}}
    close $components
    puts "AREA_POWER_NATIVE_EVIDENCE_DONE weight_macros=$weight_count input_macros=$input_count"
}
