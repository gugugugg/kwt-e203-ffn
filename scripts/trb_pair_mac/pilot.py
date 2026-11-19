"""Common SS/EMA2 synthesis, mapped replay, timing and averaged power."""
import json
import re
import sys

from common import BASE, ROOT

sys.path.insert(0, str(ROOT/"scripts/trb_128mac"))
from native import job

SDC = r"""
create_clock -name clk -period 6.666666 [get_ports clk]
set inputs [remove_from_collection [all_inputs] [get_ports clk]]
set_input_transition 0.1 $inputs
set_input_delay -clock clk -max 0.7 $inputs
set_input_delay -clock clk -min 0.7 $inputs
set_output_delay -clock clk -max 0.7 [all_outputs]
set_output_delay -clock clk -min 0.7 [all_outputs]
set_load 0.002856 [all_outputs]
"""

LIBRARIES = r"""
set standard [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set macro_libraries [list]
foreach macro {RAMSP128X16 RAMSP1024X16 RAMSP4096X16} {
    lappend macro_libraries [exec find build/server/technology -name [format "%s_ss_0p99v_0p99v_125c.db" $macro]]
}
"""


def relative(path):
    return path.relative_to(ROOT).as_posix()


def save_script(folder, filename, text):
    path = folder / filename
    path.write_text(text)
    return path


def synthesis(folder, top, sources):
    p = relative(folder)
    script = "\n".join([
        "set_host_options -max_cores 4", LIBRARIES,
        "set_app_var target_library [list $standard]",
        "set_app_var synthetic_library dw_foundation.sldb",
        "set_app_var link_library [concat [list * $standard dw_foundation.sldb] $macro_libraries]",
        "define_design_lib WORK -path %s/work" % p,
        "analyze -format sverilog [list %s]" % " ".join(relative(path) for path in sources),
        "elaborate " + top, "current_design " + top, "link", "uniquify", SDC,
        "set_fix_hold [get_clocks clk]",
        "compile_ultra -no_autoungroup",
        "change_names -rules verilog -hierarchy",
        "redirect %s/area.rpt {report_area -hierarchy}" % p,
        "redirect %s/resources.rpt {report_resources -hierarchy}" % p,
        "write -format verilog -hierarchy -output %s/netlist.v" % p,
        'puts "PAIR_PILOT_SYNTH_DONE"', "exit",
    ])
    log = folder/"synth.log"
    netlist = folder/"netlist.v"
    if not (netlist.is_file() and log.is_file() and "PAIR_PILOT_SYNTH_DONE" in log.read_text()):
        job(["dc_shell", "-f", save_script(folder,"synth.tcl",script)], log)
    return netlist


def replay(folder, top, netlist, bench, pass_marker):
    activity = folder/"activity.saif"
    sim_log = folder/"run.log"
    if activity.is_file() and sim_log.is_file() and pass_marker in sim_log.read_text():
        return activity
    original = (BASE/"gate-activity/gate_activity.f").read_text().splitlines()
    models = [line for line in original if not (line.endswith("/netlist.v") or line.endswith("gate_activity_tb.sv"))]
    filelist = folder/"files.f"
    filelist.write_text("\n".join(models+[relative(netlist),relative(bench)])+"\n")
    sim = folder/"sim"
    if not sim.is_file():
        job(["vcs","-full64","-sverilog","+delay_mode_distributed","+notimingcheck","-timescale=1ns/1fs",
             "+define+ARM_UD_MODEL+KWT_UNIFIED_GATE+DISABLE_SV_ASSERTION=1","-debug_access+all",
             "-top",top,"-f",filelist,"-Mdir="+str(folder/"csrc"),"-o",sim],folder/"compile.log")
    job([sim,"+SAIF="+relative(activity)],sim_log)
    assert pass_marker in sim_log.read_text() and activity.is_file()
    return activity


def power(folder, top, bench_top, netlist, activity):
    p = relative(folder)
    script = "\n".join([
        "set_host_options -max_cores 8", LIBRARIES,
        "set link_path [concat [list * $standard] $macro_libraries]",
        "set_app_var power_enable_analysis true", "set_app_var power_analysis_mode averaged",
        "read_verilog "+relative(netlist), "current_design "+top, "link_design", SDC,
        "update_timing",
        "set path [get_timing_paths -delay_type max -max_paths 1]",
        'puts "PAIR_SETUP_NS=[get_attribute $path slack]"',
        "set path [get_timing_paths -delay_type min -max_paths 1]",
        'puts "PAIR_HOLD_NS=[get_attribute $path slack]"',
        "redirect %s/timing.rpt {report_constraint -all_violators -significant_digits 6}" % p,
        "redirect %s/gating_setup.rpt {report_constraint -clock_gating_setup -verbose -significant_digits 6}" % p,
        "redirect %s/gating_hold.rpt {report_constraint -clock_gating_hold -verbose -significant_digits 6}" % p,
        'if {![read_saif -strip_path %s/dut %s]} {error "Replay SAIF annotation failed"}' %
        (bench_top,relative(activity)),
        "update_power",
        "redirect %s/power.rpt {report_power -verbose -hierarchy}" % p,
        "set report "+p, "source scripts/server/export_optimization_power.tcl",
        "redirect %s/annotation.rpt {report_switching_activity}" % p,
        "set leaf [open %s/leaf.tsv w]" % p,
        'puts $leaf "name\tref\tarea\tpower_w"',
        "foreach_in_collection cell [get_cells -hierarchical -filter {is_hierarchical == false}] {",
        '  puts $leaf "[get_object_name $cell]\t[get_attribute $cell ref_name]\t[get_attribute $cell area]\t[get_attribute $cell total_power]"',
        "}", "close $leaf", 'puts "PAIR_PILOT_POWER_DONE"', "exit",
    ])
    log = folder/"power.log"
    job(["pt_shell","-f",save_script(folder,"power.tcl",script)],log)
    content = log.read_text()
    assert "PAIR_PILOT_POWER_DONE" in content
    result = json.loads((folder/"power_values.json").read_text())
    for field in ("setup","hold"):
        match = re.search("PAIR_"+field.upper()+"_NS=([-0-9.eE]+)",content)
        result[field+"_slack_ns"] = float(match[1]) if match else None
    area = (folder/"area.rpt").read_text()
    result["mapped_area_um2"] = float(re.search(r"Total cell area:\s+([\d.]+)",area)[1])
    return result


def run(folder, top, bench_top, source, bench, pass_marker, extras=()):
    sources = [ROOT/"rtl/ffn/kwt_ffn_clock_gate.sv",source]+list(extras)
    netlist = synthesis(folder,top,sources)
    activity = replay(folder,bench_top,netlist,bench,pass_marker)
    return power(folder,top,bench_top,netlist,activity)

