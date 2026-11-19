"""Measure the FIFO entry clock ECO on the native E203 gate flow."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re

from fifo_eco import BASE, BITS, CHECKPOINT, NAME, PARENT, REPORT, ROOT, TAG, generate, rtl
import native_run as param

native, capture, power, private = param.native, param.capture, param.power, param.private
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
set fifo_regs [get_cells -hierarchical -quiet -filter {full_name =~ */core/out_word_reg_*}]
set fifo_gates [get_cells -hierarchical -quiet -filter {full_name =~ */core/fifo_entry_*_gate}]
set fifo_d [get_pins -of_objects $fifo_regs -filter {full_name =~ */D}]
set fifo_q [get_pins -of_objects $fifo_regs -filter {full_name =~ */Q}]
set fifo_en [get_pins -of_objects $fifo_gates -filter {full_name =~ */E}]
if {[sizeof_collection $fifo_d] != 1088 || [sizeof_collection $fifo_q] != 1088 ||
    [sizeof_collection $fifo_en] != 17} {error "FIFO pin selection failed"}
redirect $report/fifo_paths.rpt {
    foreach delay {max min} {
        puts "FIFO_WRITE_$delay"
        report_timing -to $fifo_d -delay_type $delay -max_paths 12 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets
        puts "FIFO_READ_$delay"
        report_timing -from $fifo_q -delay_type $delay -max_paths 12 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets
        puts "FIFO_ENABLE_$delay"
        report_timing -to $fifo_en -delay_type $delay -max_paths 17 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets
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
puts "FIFO_TIMING setup=$assessment_setup hold=$assessment_hold registers=[sizeof_collection $fifo_regs] gates=[sizeof_collection $fifo_gates] area_delta=$area"
exit
"""
    script.write_text(tcl)
    log = folder / "pt.log"
    native.job(["pt_shell", "-f", script], log, dict(os.environ, XPIAN_CORNER="ss", XPIAN_TAG=TAG))
    setup, hold, regs, gates, delta = re.search(
        r"(?m)^FIFO_TIMING setup=(\S+) hold=(\S+) registers=(\d+) gates=(\d+) area_delta=(\S+)$",
        log.read_text()).groups()
    assert (int(regs), int(gates)) == (BITS, 17)
    paths = (folder / "fifo_paths.rpt").read_text()
    blocks = re.split(r"(?m)^FIFO_\w+_(?:max|min)$", paths)[1:]
    assert len(blocks) == 6 and all("slack (" in block for block in blocks)
    violations = {key: (folder / (key + ".rpt")).read_text().count("(VIOLATED)")
                  for key in ("constraints", "gating_setup", "gating_hold", "fifo_paths")}
    baseline_area = native.read(BASE / "timing.json")["area_mm2"]
    delta = float(delta)
    result = dict(variant=NAME, tag=TAG, setup_slack_ns=float(setup), hold_slack_ns=float(hold),
                  violations=violations, checks_passed=float(setup) >= 0 and float(hold) >= 0 and
                  not any(violations.values()), registers=BITS, gates=17, area_delta_um2=delta,
                  baseline_area_mm2=baseline_area, area_mm2=baseline_area + delta / 1e6)
    native.save(REPORT / "timing.json", result)
    print("FIFO_TIMING_RESULT", result, flush=True)


def observe(bench, words):
    core = "dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.core"
    lines = ["    integer fifo_edges[0:16], fifo_seen[0:16];",
             "    reg [16:0] fifo_expected;",
             "    reg fifo_sample;",
             "    initial for(integer w=0;w<17;w++) begin fifo_edges[w]=0;fifo_seen[w]=0;end",
             "    always @(posedge clk) begin",
             "        fifo_sample=activity_window;",
             "        if(fifo_sample) begin"]
    for index, word in enumerate(words):
        lines.append("            fifo_expected[%d]=%s.%s.E;" % (index, core, word["gate"]))
    lines += ["        end", "    end",
              "    always @(negedge clk) if(fifo_sample) begin",
              "        for(integer w=0;w<17;w++) begin",
              "            if(fifo_edges[w]-fifo_seen[w] !== int'(fifo_expected[w]))",
              '                $fatal(1,"FIFO_GATE_EDGE_MISMATCH entry=%0d cycle=%0d",w,cycles-start_cycle);',
              "            fifo_seen[w]=fifo_edges[w];",
              "        end", "    end"]
    for index, word in enumerate(words):
        lines.append("    always @(posedge %s.%s.Q) if(activity_window) fifo_edges[%d]++;" %
                     (core, word["gate"], index))
    bench = capture.replace(bench, "    string vcd_path;", "    string vcd_path;\n" + "\n".join(lines))
    checks = """
            for(integer w=0;w<17;w++)
                if(fifo_edges[w]!=(w<12?373:372))
                    $fatal(1,"FIFO_GATE_WRITE_COUNT entry=%0d actual=%0d",w,fifo_edges[w]);
            $display("FIFO_GATE_PASS entries=17 writes=6336");
"""
    return capture.replace(bench, "            wait(task_done==task_number);",
                           "            wait(task_done==task_number);\n" + checks)


def measure():
    timing_result = native.read(REPORT / "timing.json")
    if not timing_result["checks_passed"]:
        raise RuntimeError("Inspect FIFO timing reports before cold replay")
    original_prepare = capture.prepare_bench
    words = native.read(REPORT / "eco.json")["words"]
    param_words = native.read(BASE / "eco.json")["words"]
    macros = native.read(param.BASE / "eco.json")["macro_gates"]

    def prepare(screen):
        files = original_prepare(screen)
        bench = capture.WORK / "gate_activity_tb.sv"
        text = private.add_observation(bench.read_text(), macros)
        text = param.observe(text, param_words)
        bench.write_text(observe(text, words))
        return files

    capture.prepare_bench = prepare
    binary = capture.build(dict(tag=TAG))
    cases = native.read(private.BASE / "cpu-result.json")["cases"]
    power.POWER.mkdir(exist_ok=True)
    tcl = power.build_tcl()

    def replay(row):
        activity = capture.capture(binary, row)
        text = (capture.WORK / ("run_%02d.log" % row["case"])).read_text()
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
    print("FIFO_POWER_DONE", mean, throughput, flush=True)


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
