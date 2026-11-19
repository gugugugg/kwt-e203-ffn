"""Assess and measure the operand parity ECO in the native gate flow."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re

from parity_eco import BASE, CHECKPOINT, NAME, PARENT, REPORT, ROOT, TAG, generate, rtl
import run_fifo as fifo

native, capture, power, private = fifo.native, fifo.capture, fifo.power, fifo.private
param = fifo.param
NETLIST = CHECKPOINT / "netlist.v"
PARENT_NETLIST = ROOT / "build/server" / ("complete_soc_sm40_opt_" + PARENT + "_final_ss_ema2/netlist.v")


def timing():
    folder = REPORT / "sta"
    folder.mkdir(exist_ok=True)
    script = folder / "assess.tcl"
    tcl = (native.OUT / "eda/time.tcl").read_text().split("if {$assessment_setup < 0", 1)[0]
    tcl = re.sub(r"(?m)^set report .+$", "set report " + folder.relative_to(ROOT).as_posix(), tcl)
    manifest = native.read(REPORT / "eco.json")
    refs = set(manifest["added"]) | set(manifest["removed"])
    counts = " ".join("%s %d" % (cell, manifest["added"].get(cell, 0) - manifest["removed"].get(cell, 0))
                      for cell in sorted(refs))
    tcl += """
redirect $report/gating_setup.rpt {report_constraint -clock_gating_setup -verbose -significant_digits 9}
redirect $report/gating_hold.rpt {report_constraint -clock_gating_hold -verbose -significant_digits 9}
set banks [get_cells -hierarchical -quiet -filter {full_name =~ */core/operands_reg_* || full_name =~ */core/operand_parity_t00_bank1_ff*}]
set first [get_cells -hierarchical -quiet -filter {full_name =~ */core/operands_reg_1__* || full_name =~ */core/operand_parity_t00_bank1_ff*}]
set gates [get_cells -hierarchical -quiet -filter {full_name =~ */core/operand_parity_t*_gate?}]
set sels [get_cells -hierarchical -quiet -filter {full_name =~ */core/operand_parity_t*_sel_ff}]
set macs [get_cells -hierarchical -quiet -filter {full_name =~ */core/weight_columns_*__acc_a_reg_* || full_name =~ */core/weight_columns_*__acc_b_reg_*}]
set bank_d [get_pins -of_objects $banks -filter {full_name =~ */D}]
set bank_q [get_pins -of_objects $banks -filter {full_name =~ */Q}]
set first_d [get_pins -of_objects $first -filter {full_name =~ */D}]
set gate_e [get_pins -of_objects $gates -filter {full_name =~ */E}]
set sel_q [get_pins -of_objects $sels -filter {full_name =~ */Q}]
set mac_d [get_pins -of_objects $macs -filter {full_name =~ */D}]
set phase_q [get_pins -hierarchical -quiet -filter {full_name =~ */core/operand_parity_phase_ff/Q}]
if {[sizeof_collection $bank_d] != 2048 || [sizeof_collection $bank_q] != 2048 ||
    [sizeof_collection $first_d] != 128 || [sizeof_collection $gate_e] != 32 ||
    [sizeof_collection $sel_q] != 16 || [sizeof_collection $phase_q] != 1 ||
    [sizeof_collection $mac_d] == 0} {error "Operand pin selection failed"}
proc parity_paths {delay args} {
    report_timing -delay_type $delay -max_paths 12 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets {*}$args
}
redirect $report/operand_paths.rpt {
    foreach delay {max min} {
        puts "PARITY_INPUT_$delay"
        parity_paths $delay -to $first_d
        puts "PARITY_TRANSFER_$delay"
        parity_paths $delay -from $bank_q -to $bank_d
        puts "PARITY_PHASE_$delay"
        parity_paths $delay -from $phase_q -to $gate_e
        puts "PARITY_GATE_$delay"
        parity_paths $delay -to $gate_e
        puts "PARITY_BANK_MAC_$delay"
        parity_paths $delay -from $bank_q -to $mac_d
        puts "PARITY_SELECT_MAC_$delay"
        parity_paths $delay -from $sel_q -to $mac_d
    }
}
set area 0.0
set stream [open $report/area_delta.rpt w]
foreach {reference count} {""" + counts + """} {
    set cells [get_lib_cells -quiet */$reference]
    if {[sizeof_collection $cells] != 1} {error "Expected one linked area for $reference"}
    set value [get_attribute $cells area]
    puts $stream "$reference $count $value"
    set area [expr {$area + $count * $value}]
}
close $stream
puts "PARITY_TIMING setup=$assessment_setup hold=$assessment_hold area_delta=$area"
exit
"""
    script.write_text(tcl)
    log = folder / "pt.log"
    native.job(["pt_shell", "-f", script], log, dict(os.environ, XPIAN_CORNER="ss", XPIAN_TAG=TAG))
    setup, hold, delta = map(float, re.search(
        r"(?m)^PARITY_TIMING setup=(\S+) hold=(\S+) area_delta=(\S+)$", log.read_text()).groups())
    paths = (folder / "operand_paths.rpt").read_text()
    sections = re.split(r"(?m)^PARITY_(\w+_(?:max|min))$", paths)
    assert len(sections) == 25, sections[:3]
    margins = {}
    for label, body in zip(sections[1::2], sections[2::2]):
        margins[label] = min(map(float, re.findall(r"slack \((?:MET|VIOLATED)\)\s+(-?[.\d]+)", body)))
    violations = {key: (folder / (key + ".rpt")).read_text().count("(VIOLATED)")
                  for key in ("constraints", "gating_setup", "gating_hold", "operand_paths")}
    baseline_area = native.read(BASE / "timing.json")["area_mm2"]
    result = dict(variant=NAME, tag=TAG, setup_slack_ns=setup, hold_slack_ns=hold,
                  path_slack_ns=margins, violations=violations,
                  checks_passed=setup >= 0 and hold >= 0 and not any(violations.values()),
                  area_delta_um2=delta, baseline_area_mm2=baseline_area,
                  area_mm2=baseline_area + delta / 1e6)
    native.save(REPORT / "timing.json", result)
    print("PARITY_TIMING_RESULT", result, flush=True)


def observe(bench, taps):
    core = "dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.core"
    lines = ["    integer op_edges[0:31], op_seen[0:31];",
             "    reg [31:0] op_expected;",
             "    reg op_sample;",
             "    initial for(integer i=0;i<32;i++) begin op_edges[i]=0;op_seen[i]=0;end",
             "    always @(posedge clk) begin",
             "        op_sample=activity_window;",
             "        if(op_sample) begin"]
    for tap in taps:
        for bank, enable in enumerate(tap["enables"]):
            i = 2 * tap["index"] + bank
            lines.append("            op_expected[%d]=%s.%s;" % (i, core, enable))
    lines += ["        end", "    end",
              "    always @(negedge clk) if(op_sample) begin",
              "        for(integer i=0;i<32;i++) begin",
              "            if(op_edges[i]-op_seen[i] !== int'(op_expected[i]))",
              '                $fatal(1,"OPERAND_GATE_EDGE_MISMATCH bank=%0d cycle=%0d",i,cycles-start_cycle);',
              "            op_seen[i]=op_edges[i];",
              "        end", "    end"]
    for tap in taps:
        for bank, clock in enumerate(tap["clocks"]):
            i = 2 * tap["index"] + bank
            lines.append("    always @(posedge %s.%s) if(activity_window) op_edges[%d]++;" % (core, clock, i))
    bench = capture.replace(bench, "    string vcd_path;", "    string vcd_path;\n" + "\n".join(lines))
    checks = """
            for(integer i=0;i<16;i++)
                if(op_edges[2*i]+op_edges[2*i+1]!=12800)
                    $fatal(1,"OPERAND_GATE_WRITE_COUNT tap=%0d actual=%0d",i,op_edges[2*i]+op_edges[2*i+1]);
            $display("OPERAND_GATE_PASS taps=16 writes_per_tap=12800");
"""
    return capture.replace(bench, "            wait(task_done==task_number);",
                           "            wait(task_done==task_number);\n" + checks)


def measure():
    timing_result = native.read(REPORT / "timing.json")
    if not timing_result["checks_passed"]:
        raise RuntimeError("Inspect operand timing before cold replay")
    original_prepare = capture.prepare_bench
    taps = native.read(REPORT / "eco.json")["taps"]
    fifo_words = native.read(BASE / "eco.json")["words"]
    param_words = native.read(fifo.BASE / "eco.json")["words"]
    macros = native.read(param.BASE / "eco.json")["macro_gates"]

    def prepare(screen):
        files = original_prepare(screen)
        bench = capture.WORK / "gate_activity_tb.sv"
        text = private.add_observation(bench.read_text(), macros)
        text = param.observe(text, param_words)
        text = fifo.observe(text, fifo_words)
        bench.write_text(observe(text, taps))
        return files

    capture.prepare_bench = prepare
    binary = capture.build(dict(tag=TAG))
    cases = native.read(private.BASE / "cpu-result.json")["cases"]
    power.POWER.mkdir(exist_ok=True)
    tcl = power.build_tcl()

    def replay(row):
        activity = capture.capture(binary, row)
        text = (capture.WORK / ("run_%02d.log" % row["case"])).read_text()
        assert "OPERAND_GATE_PASS taps=16 writes_per_tap=12800" in text
        assert "FIFO_GATE_PASS entries=17 writes=6336" in text
        assert "PARAM_WORD_GATE_PASS words=80 writes=320" in text
        stats = {role: int(edges) for role, edges in re.findall(
            r"PRIVATE_SRAM_EDGES (\w+) reads=\d+ writes=\d+ edges=(\d+)", text)}
        assert stats == private.ACTIVE_COUNTS
        return activity

    def evaluate(activity):
        return power.measure(tcl, TAG, activity, "SAIF", ROOT / activity["saif"])

    settings = native.settings()
    with ThreadPoolExecutor(max_workers=settings["cpu_case_workers"]) as sims:
        with ThreadPoolExecutor(max_workers=settings["power_case_workers_per_candidate"]) as pt:
            captures, jobs = [], []
            for job in as_completed([sims.submit(replay, row) for row in cases]):
                activity = job.result()
                captures.append(activity)
                jobs.append(pt.submit(evaluate, activity))
            captures.sort(key=lambda row: row["case"])
            native.save(capture.WORK / "captures.json", dict(variant=NAME, tag=TAG, captures=captures))
            measurements = sorted((job.result() for job in jobs), key=lambda row: row["case"])
    assert len(measurements) == 12
    cycles = sum(row["cycles"] for row in measurements)
    weighted = {key: sum(row[key] * row["cycles"] for row in measurements) / cycles for key in power.FIELDS}
    throughput = 12 * 150000000 / cycles
    baseline = native.read(BASE / "result.json")
    previous = baseline["mean_power_w"]
    mean = weighted["total_w"]
    assert native.read(ROOT / "constraints/ffn_selected.json")["variant"] == "ffn_sg_reuse"
    result = dict(variant=NAME, tag=TAG, cycles_total=cycles, throughput_per_second=throughput,
                  mean_power_w=mean, mean_energy_j=mean / throughput, timing=timing_result,
                  baseline_power_w=previous, baseline_energy_j=baseline["mean_energy_j"],
                  meets_throughput=cycles < 180000, power_reduced=mean < previous,
                  reduction_w=previous - mean, reduction_percent=100 * (previous - mean) / previous,
                  weighted_power=weighted, measurements=measurements, release="ffn_sg_reuse")
    native.save(REPORT / "result.json", result)
    print("PARITY_POWER_DONE", mean, throughput, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("timing", "measure", "all"))
    args = parser.parse_args()
    param.REPORT = REPORT
    param.bind()
    REPORT.mkdir(parents=True, exist_ok=True)
    native.preflight()
    if args.stage in ("timing", "all"):
        if not NETLIST.is_file():
            rtl()
            generate(PARENT_NETLIST, NETLIST)
        timing()
    if args.stage in ("measure", "all"):
        measure()
