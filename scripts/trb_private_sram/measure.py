"""Private SRAM clock-only ECO on the frozen 4x32 mapped design."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"scripts/trb_128mac"))
import native
import gate_activity as capture
import gate_power as power

NAME = "ffn_trb_4x32_private_sram"
BASE = native.REPORT
REPORT = ROOT/"reports/optimization"/NAME
TAG = "opt_" + NAME + "_final_ss_ema2"
CHECKPOINT = ROOT/"build/server"/("complete_soc_sm40_"+TAG)
CELL_GATE = "CLKLANAQV1_12TR40"
CELL_INV = "CLKINV0_12TR40"
ROLE_COUNTS = {"input":8, "weight":32, "result":8}
ACTIVE_COUNTS = {"input":57024, "weight":229376, "result":50688}

CORE = re.compile(r"(?ms)(^module kwt_threebank_core\b)(.*?)(^endmodule)")
MACRO = re.compile(r"(?ms)\b(RAMSP(?:128|1024)X16)\s+(\w+)\s*\((.*?)\);")


def bind():
    native.REPORT = REPORT
    capture.WORK = REPORT/"gate-activity"
    capture.RESULTS = capture.WORK/"results"
    power.REPORT = REPORT
    power.CAPTURE = capture.WORK
    power.POWER = REPORT/"gate-power"


def base_screen():
    return native.read(BASE/"final-screen.json")


def netlist_path(tag):
    return ROOT/"build/server"/("complete_soc_sm40_"+tag)/"netlist.v"


def materialize_rtl():
    source = ROOT/"build/optimization/rtl_sources"/native.NAME/"encoder/kwt_threebank_core.sv"
    text = source.read_text()
    for enable, cell in (("weight_read[col]||wr","RAMSP128X16"),("wr||input_read[bank]","RAMSP1024X16"),
                         ("rd||wr","RAMSP128X16")):
        before = "%s memory(.CLK(clk),.CEN(!(%s))" % (cell,enable)
        after = ("wire sram_clk;\n        kwt_ffn_clock_gate sram_gate(.clk(clk),.enable(%s),"
                 ".test_enable(1'b0),.gated_clk(sram_clk));\n        "
                 "%s memory(.CLK(sram_clk),.CEN(!(%s))" % (enable,cell,enable))
        text = capture.replace(text,before,after)
    REPORT.mkdir(parents=True,exist_ok=True)
    (REPORT/"kwt_threebank_core.sv").write_text(text)


def materialize():
    frozen = base_screen()
    assert frozen["timing_passed"]
    old = netlist_path(frozen["tag"]).read_text()
    match = CORE.search(old)
    assert match and len(CORE.findall(old)) == 1
    body = match[2]
    rows, declarations, instances = [], [], []

    def gate_macro(cell):
        ref, name, pins = cell.groups()
        cen = re.search(r"\.CEN\(([^()]+)\)",pins)[1]
        clock = re.search(r"\.CLK\(([^()]+)\)",pins)
        assert clock[1].strip()=="clk", name
        role = name.split("_")[0]
        stem = "private_sram_" + name
        en, ck = stem+"_en", stem+"_clk"
        declarations.append("  wire %s, %s;"%(en,ck))
        instances.extend(("  %s %s_inv (.I(%s), .ZN(%s));"%(CELL_INV,stem,cen,en),
                          "  %s %s_gate (.CK(clk), .E(%s), .TE(1'b0), .Q(%s));"%(CELL_GATE,stem,en,ck)))
        rows.append(dict(role=role, reference=ref, instance=name, enable_from_cen=cen.strip(),
                         inverter=stem+"_inv", gate=stem+"_gate", clock=ck, original_clock_pin=clock[0]))
        return cell[0][:cell.start(3)-cell.start()] + pins[:clock.start(1)] + ck + pins[clock.end(1):] + ");"

    new_body = MACRO.sub(gate_macro, body)
    assert Counter(row["role"] for row in rows) == ROLE_COUNTS
    # The replacement is confined to the private core. Reversing its clock
    # rewires recovers that module byte-for-byte before adding the new cells.
    recovered = new_body
    for row in rows:
        marker = ".CLK("+row["clock"]+")"
        assert recovered.count(marker) == 1
        recovered = recovered.replace(marker, row["original_clock_pin"])
    assert recovered == body
    # Declare the new nets before the first instance that references them.
    first_wire = re.search(r"(?m)^\s*wire\s",new_body).start()
    new_body = new_body[:first_wire]+"\n"+"\n".join(declarations)+"\n"+new_body[first_wire:]
    candidate = old[:match.start(2)]+new_body+"\n"+"\n".join(instances)+"\n"+old[match.end(2):]
    assert old[:match.start(2)] == candidate[:match.start(2)] and candidate.endswith(old[match.end(2):])
    CHECKPOINT.mkdir(parents=True, exist_ok=True)
    path = CHECKPOINT/"netlist.v"
    path.write_text(candidate)
    native.save(REPORT/"eco.json",dict(variant=NAME, tag=TAG, parent_tag=frozen["tag"], macro_gates=rows,
                                      source_netlist=str(netlist_path(frozen["tag"]).relative_to(ROOT)),
                                      candidate_netlist=str(path.relative_to(ROOT)),
                                      unrelated_netlist_unchanged=True))
    print("PRIVATE_SRAM_ECO_READY",len(rows),flush=True)


def make_timing_script():
    # Reuse the complete-SoC assessment setup and libraries at the same corner.
    text = (native.OUT/"eda/time.tcl").read_text().split('if {$assessment_setup < 0',1)[0]
    folder = REPORT/"sta"
    folder.mkdir(exist_ok=True)
    text, count = re.subn(r"(?m)^set report .+$","set report "+folder.relative_to(ROOT).as_posix(),text)
    assert count == 1
    text += r"""
redirect $report/clock_gating_setup.rpt {report_constraint -clock_gating_setup -verbose -significant_digits 9}
redirect $report/clock_gating_hold.rpt {report_constraint -clock_gating_hold -verbose -significant_digits 9}
set private_macros [get_cells -hierarchical -quiet -filter {(full_name =~ */core/input_memory_* || full_name =~ */core/weight_columns_* || full_name =~ */core/result_memory_*) && (ref_name == RAMSP128X16 || ref_name == RAMSP1024X16)}]
set private_inputs [get_pins -quiet -of_objects $private_macros -filter {direction == in && full_name !~ */CLK}]
set private_outputs [get_pins -quiet -of_objects $private_macros -filter {direction == out}]
set added [get_cells -hierarchical -quiet -filter {full_name =~ */core/private_sram_*_inv || full_name =~ */core/private_sram_*_gate}]
set area 0.0
foreach_in_collection cell $added {
    set area [expr {$area + [get_attribute $cell area]}]
}
redirect $report/private_paths.rpt {
    foreach delay {max min} {
        puts "PRIVATE_MACRO_INPUT_$delay"
        report_timing -to $private_inputs -delay_type $delay -max_paths 15 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets
        puts "PRIVATE_MACRO_OUTPUT_$delay"
        report_timing -from $private_outputs -delay_type $delay -max_paths 15 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded -input_pins -nets
    }
}
puts "PRIVATE_TIMING setup=$assessment_setup hold=$assessment_hold macros=[sizeof_collection $private_macros] cells=[sizeof_collection $added] area=$area"
exit
"""
    script = folder/"assess.tcl"
    script.write_text(text)
    return script


def timing():
    script = make_timing_script()
    folder = script.parent
    log = folder/"pt.log"
    native.job(["pt_shell","-f",script],log,dict(os.environ,XPIAN_CORNER="ss",XPIAN_TAG=TAG))
    fields = re.search(r"(?m)^PRIVATE_TIMING setup=(\S+) hold=(\S+) macros=(\d+) cells=(\d+) area=(\S+)$",
                       log.read_text()).groups()
    setup, hold, macros, cells, delta = float(fields[0]), float(fields[1]), int(fields[2]), int(fields[3]), float(fields[4])
    assert (macros,cells)==(48,96)
    flags = {name:(folder/(name+".rpt")).read_text().count("(VIOLATED)") for name in
             ("constraints","clock_gating_setup","clock_gating_hold","private_paths")}
    paths=(folder/"private_paths.rpt").read_text()
    for group in ("INPUT_max","OUTPUT_max","INPUT_min","OUTPUT_min"):
        assert "slack (" in re.split(r"\nPRIVATE_MACRO_",paths.split("PRIVATE_MACRO_"+group,1)[1],1)[0],group
    baseline = base_screen()["area"]["accelerator_budget_including_shared_interface_mm2"]
    report = dict(variant=NAME,tag=TAG,setup_slack_ns=setup,hold_slack_ns=hold,
                  violations=flags,checks_passed=setup>=0 and hold>=0 and not any(flags.values()),
                  private_macros=macros,added_cells=cells,added_area_um2=delta,
                  baseline_area_mm2=baseline,area_mm2=baseline+delta/1e6)
    native.save(REPORT/"timing.json",report)
    print("PRIVATE_TIMING_RESULT",report,flush=True)
    if not report["checks_passed"]:
        raise RuntimeError("Inspect private SRAM timing before replay")


def add_observation(bench, rows):
    core = "dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.core"
    lines = ["    integer private_reads[0:47], private_writes[0:47], private_edges[0:47];",
             "    integer private_expected[0:47], private_previous[0:47];",
             "    bit private_sample;",
             "    initial for(integer m=0;m<48;m=m+1) begin",
             "        private_reads[m]=0;private_writes[m]=0;private_edges[m]=0;",
             "        private_expected[m]=0;private_previous[m]=0;",
             "    end",
             "    always @(posedge clk) begin",
             "        private_sample=activity_window;",
             "        if(private_sample) begin"]
    for idx,row in enumerate(rows):
        cell=core+"."+row["instance"]
        lines.extend(("            if ($isunknown(%s.CEN)) $fatal(1,\"Unknown private SRAM CEN %d\");"%(cell,idx),
                      "            private_expected[%d]=!%s.CEN;"%(idx,cell),
                      "            if (!%s.CEN) begin"%cell,
                      "                if (%s.GWEN===1'b1) private_reads[%d]++;"%(cell,idx),
                      "                else if (%s.GWEN===1'b0) private_writes[%d]++;"%(cell,idx),
                      "                else $fatal(1,\"Unknown private SRAM GWEN %d\");"%idx,
                      "            end"))
    lines.extend(("        end","    end",
                  "    always @(negedge clk) if(private_sample) begin",
                  "        for(integer m=0;m<48;m=m+1) begin",
                  "            if(private_edges[m]-private_previous[m]!=private_expected[m])",
                  "                $fatal(1,\"Private SRAM gate edge mismatch bank=%0d cycle=%0d\",m,cycles-start_cycle);",
                  "            private_previous[m]=private_edges[m];",
                  "        end",
                  "    end"))
    for idx,row in enumerate(rows):
        cell=core+"."+row["instance"]
        lines.append("    always @(posedge %s.CLK) if(activity_window) private_edges[%d]++;"%(cell,idx))
    prints=[]
    for role in ROLE_COUNTS:
        indexes=[i for i,row in enumerate(rows) if row["role"]==role]
        sums=["+".join("%s[%d]"%(key,idx) for idx in indexes) for key in ("private_reads","private_writes","private_edges")]
        prints.append('            $display("PRIVATE_SRAM_EDGES %s reads=%%0d writes=%%0d edges=%%0d",%s);'%
                      (role,",".join(sums)))
    bench=capture.replace(bench,"    string vcd_path;","    string vcd_path;\n"+"\n".join(lines))
    return capture.replace(bench,"            wait(task_done==task_number);",
                           "            wait(task_done==task_number);\n"+"\n".join(prints))


def simulate_and_measure():
    measured_timing = native.read(REPORT/"timing.json")
    assert measured_timing["checks_passed"]
    original_prepare = capture.prepare_bench
    rows = native.read(REPORT/"eco.json")["macro_gates"]

    def prepare(screen):
        filelist = original_prepare(screen)
        bench = capture.WORK/"gate_activity_tb.sv"
        bench.write_text(add_observation(bench.read_text(),rows))
        return filelist

    capture.prepare_bench = prepare
    binary = capture.build(dict(tag=TAG))
    cpu = native.read(BASE/"cpu-result.json")
    cases = cpu["cases"]
    power.POWER.mkdir(exist_ok=True)
    tcl = power.build_tcl()

    def replay(row):
        activity = capture.capture(binary,row)
        text=(capture.WORK/("run_%02d.log"%row["case"])).read_text()
        stats={role:dict(reads=int(rd),writes=int(wr),edges=int(edges))
               for role,rd,wr,edges in re.findall(r"PRIVATE_SRAM_EDGES (\w+) reads=(\d+) writes=(\d+) edges=(\d+)",text)}
        assert {k:v["edges"] for k,v in stats.items()}==ACTIVE_COUNTS
        assert all(v["reads"]+v["writes"]==v["edges"] for v in stats.values())
        activity["private_sram"]=stats
        return activity

    def measure(activity):
        return power.measure(tcl,TAG,activity,"SAIF",ROOT/activity["saif"])

    with ThreadPoolExecutor(max_workers=native.settings()["cpu_case_workers"]) as simulators:
        with ThreadPoolExecutor(max_workers=native.settings()["power_case_workers_per_candidate"]) as analysts:
            captures, futures = [], []
            for activity in simulators.map(replay,cases):
                captures.append(activity)
                futures.append(analysts.submit(measure,activity))
            native.save(capture.WORK/"captures.json",dict(variant=NAME,tag=TAG,captures=captures))
            report=[job.result() for job in futures]
    old = native.read(BASE/"gate-power/result.json")
    assert len(report)==len(cases)==len(old["measurements"])==12
    cycles = sum(case["cycles"] for case in report)
    assert cycles==old["cycles_total"] and cycles<=180000
    weighted={key:sum(case[key]*case["cycles"] for case in report)/cycles for key in power.FIELDS}
    mean=weighted["total_w"]
    previous=old["mean_power_w"]
    throughput=12*150000000/cycles
    assert native.read(ROOT/"constraints/ffn_selected.json")["variant"]=="ffn_sg_reuse"
    native.save(REPORT/"result.json",dict(variant=NAME,tag=TAG,timing=measured_timing,cycles_total=cycles,
                throughput_per_second=throughput,mean_power_w=mean,mean_energy_j=mean/throughput,
                baseline_mean_power_w=previous,baseline_mean_energy_j=old["mean_energy_j"],
                reduction_w=previous-mean,reduction_percent=100*(previous-mean)/previous,
                whole_soc_power_reduced=mean<previous,weighted_power=weighted,measurements=report,
                private_macro_edges_per_case=ACTIVE_COUNTS,activity="fresh final-netlist SAIF, PTPX averaged",
                release="ffn_sg_reuse"))
    print("PRIVATE_SRAM_POWER_DONE",mean,throughput,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-only",action="store_true")
    parser.add_argument("--rtl-only",action="store_true")
    args=parser.parse_args()
    if args.rtl_only:
        materialize_rtl()
        return
    bind()
    native.preflight()
    if not args.replay_only and not (CHECKPOINT/"netlist.v").is_file():
        materialize_rtl()
        materialize()
    if not args.replay_only:
        timing()
    simulate_and_measure()


if __name__=="__main__":
    main()

