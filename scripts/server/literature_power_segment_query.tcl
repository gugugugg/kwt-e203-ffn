set tag $env(XPIAN_TAG)
set cell_name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db
set ram_corner ss_0p99v_0p99v_125c
set platform_libraries [glob build/server/technology/platform_ram_db/*.db]
set cell_library [exec find build/server/technology -name $cell_name]
set link_path [list * $cell_library build/server/technology/ram_db/RAMSP1024X16_${ram_corner}.db build/server/technology/ram_db/RAMSP128X16_${ram_corner}.db]
set link_path [concat $link_path $platform_libraries]
read_verilog build/server/complete_soc_sm40_$tag/netlist.v
current_design kwt_complete_soc
link_design

proc b_query_segment {f kind name} {
    puts $f "GROUP $kind $name"
    if {$kind == "pin"} {
        set target [get_pins -quiet $name]
        if {[sizeof_collection $target] == 0} {
            puts $f "NO_TARGET $name"
            return
        }
        if {[get_attribute $target direction] eq "internal"} {puts $f "INTERNAL_PIN $name";return}
        set attached [get_attribute $target net]
        if {[sizeof_collection $attached] == 0} {puts $f "NO_NET $name";return}
        set segments [get_nets -quiet -segments -of_objects $target]
    } else {
        set segments [get_nets -quiet -segments $name]
    }
    if {[sizeof_collection $segments] == 0} {
        puts $f "NO_SEGMENTS $name"
        return
    }
    foreach_in_collection net $segments {
        puts $f "NET [get_object_name $net]"
    }
    set connected [get_pins -quiet -of_objects $segments]
    if {[sizeof_collection $connected] == 0} {
        puts $f "NO_CONNECTED_PINS $name"
        return
    }
    set drivers 0
    set consumers 0
    foreach_in_collection pin $connected {
        set direction [get_attribute $pin direction]
        set cell [get_cells -quiet -of_objects $pin]
        if {[sizeof_collection $cell] == 0} {
            puts $f "PIN_NO_CELL [get_object_name $pin] $direction"
            continue
        }
        set ref [get_attribute $cell ref_name]
        if {$direction == "out"} {
            incr drivers
            puts $f "DRIVER [get_object_name $pin] $ref"
            if {[string match *12TR40 $ref]} {
                set cell_pins [get_pins -quiet -of_objects $cell]
                if {[sizeof_collection $cell_pins] > 0} {
                    foreach_in_collection input $cell_pins {
                        if {[get_attribute $input direction] != "in"} {continue}
                        set nets [get_attribute $input net]
                        if {[sizeof_collection $nets] > 0} {
                            puts $f "DRIVER_INPUT [get_object_name $input] [get_object_name $nets]"
                        } else {
                            puts $f "DRIVER_INPUT_NO_NET [get_object_name $input]"
                        }
                    }
                }
            }
        } elseif {$direction == "in"} {
            incr consumers
            puts $f "CONSUMER [get_object_name $pin] $ref"
        } else {
            puts $f "OTHER_DIRECTION [get_object_name $pin] $direction $ref"
        }
    }
    if {$drivers == 0} {puts $f "NO_DRIVER $name"}
    if {$consumers == 0} {puts $f "NO_CONSUMER $name"}
}
