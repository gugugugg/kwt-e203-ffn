"""Capture exact final-netlist cold activity, including a case-one VCD."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import re

from mapped import paths, physical_probe, preload
from native import DEST, NAME, OUT, REPORT, ROOT, job, preflight, read, save, settings

WORK = REPORT / "gate-activity"
RESULTS = WORK / "results"
MARKERS = ("UNIFIED_PUBLIC_TASK_PASS", "THREEBANK_COUNTS")


def replace(source, before, after):
    assert source.count(before) == 1, before
    return source.replace(before, after)


def prepare_bench(screen):
    netlist = ROOT / "build/server" / ("complete_soc_sm40_" + screen["tag"]) / "netlist.v"
    text = netlist.read_text()
    assert re.search(r"\.wb_ack_valid\(\s*wb_ack_valid\s*\),\s*\.ld_rsp_ready_BAR\(ld_rsp_ready\),\s*"
                     r"\.wb_ack_ready_BAR\(1'b0\)", text)
    tcm, shared = paths(text)
    bench = (OUT / "complete_soc_tb.sv").read_text()
    bench = re.sub(r"(?m)^\s*wire \[31:0\] inspect_pc=.*;\n", "\n", bench)
    bench = bench.replace(" pc=%h", "").replace(",inspect_pc", "")
    lo, hi = shared[31][0], shared[31][1]
    expressions = {
        "cpu_fire": "!%s.CEN&&!%s.GWEN&&!%s.CEN&&!%s.GWEN&&%s.WEN==0&&%s.WEN==0" % (lo,lo,hi,hi,lo,hi),
        "cpu_address": "32'ha007c000+{18'b0,%s.A,2'b00}" % lo,
        "cpu_data": "{%s.D,%s.D}" % (hi, lo), "cpu_read": "1'b0",
        "result_ack": "dut.wb_ack_valid",
    }
    for field, expression in expressions.items():
        bench, count = re.subn(r"(?m)(^\s*wire (?:\[31:0\] )?"+field+r"=)[^;]*;",
                               lambda m: m[1]+expression+";", bench)
        assert count == 1, field
    bench = re.sub(r"(?m)^    wire (?:\[3:0\] cpu_mask|source_fire)=.*;\n", "", bench)
    bench = replace(bench, "    wire result_fire=dut.wb_valid&&dut.wb_ready;", physical_probe(shared))
    bench = bench.replace("int'(dut.wb_addr)", "int'(physical_result_addr)").replace(
        "dut.wb_addr,", "physical_result_addr,").replace("dut.wb_data", "physical_result_data")
    read_banks = []
    for bank in (0,1,2,3,8,9,10,11):
        lo, hi = shared[bank][0], shared[bank][1]
        read_banks.append("(!%s.CEN&&%s.GWEN&&!%s.CEN&&%s.GWEN)" % (lo,lo,hi,hi))
    bench = re.sub(r"(?m)^        if\(activity_window&&(?:source_fire|dut\.ld2_cmd_valid&&dut\.ld2_cmd_ready)\) ld_dma_reads=ld_dma_reads\+1;\n",
                   "", bench)
    bench = replace(bench, "    always @(posedge clk) if(rst_n) begin",
                    "    always @(posedge clk) if(rst_n) begin\n"
                    "        if(activity_window) ld_dma_reads=ld_dma_reads+$countones({" + ",".join(read_banks) + "});")
    begin = bench.index("        force dut.shared_memory.clk=reference_clk;")
    end = bench.index("        wait(system_reset_n===1'b1);", begin) + len("        wait(system_reset_n===1'b1);")
    bench = bench[:begin] + preload(tcm, shared[31]) + bench[end:]
    bench = re.sub(r'(?ms)`ifdef KWT_UNIFIED_GATE\n    string sdf_path;.*?`endif\n', '', bench)
    bench = replace(bench, "    bit activity_window=0,activity_enabled=0;",
                    "    bit activity_window=0,activity_enabled=0,vcd_enabled=0;\n    string vcd_path;")
    bench, count = re.subn(r'(?ms)^`ifndef KWT_UNIFIED_GATE\n`ifndef VERILATOR\n.*?^`endif\n`endif\n', '', bench)
    assert count == 3
    bench = replace(bench, "        $readmemh(firmware_path,boot_words);", """        activity_enabled=$value$plusargs("SAIF=%s",saif_path);
        vcd_enabled=$value$plusargs("VCD=%s",vcd_path);
        if(activity_enabled) begin $set_gate_level_monitoring("on");$set_toggle_region(dut);end
        $readmemh(firmware_path,boot_words);""")
    bench = replace(bench, "            host_cmd_valid=1;host_cmd_read=0;host_cmd_addr=0;host_cmd_wdata=payload[0];",
                    """            if(activity_enabled) $toggle_start();
            if(vcd_enabled) begin $dumpfile(vcd_path);$dumpvars(0,dut);end
            host_cmd_valid=1;host_cmd_read=0;host_cmd_addr=0;host_cmd_wdata=payload[0];""")
    bench = replace(bench, "            wait(task_done==task_number);", """            if(activity_enabled) begin
                $toggle_stop();
                $toggle_report(saif_path,1.0e-9,"complete_soc_tb.dut");
            end
            if(vcd_enabled) $dumpoff;
            $display("WIDE_CAPTURE_WINDOW start_ns=%0.6f end_ns=%0.6f cycles=%0d",activity_begin,activity_end,task_cycles);
            wait(task_done==task_number);""")
    source = WORK / "gate_activity_tb.sv"
    source.write_text(bench)
    models = [line for line in (OUT / "files.f").read_text().splitlines() if
              ("/mem_gen/" in line or line.startswith("/storage1/") or line.endswith("/ROM1KX32.v") or
               "scc40nll_vhsc40_rvt.v" in line)]
    files = WORK / "gate_activity.f"
    files.write_text("\n".join(models + [netlist.relative_to(ROOT).as_posix(), source.relative_to(ROOT).as_posix()]) + "\n")
    return files


def build(screen):
    WORK.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    binary = WORK / "sim"
    if not binary.exists():
        files = prepare_bench(screen)
        job(["vcs", "-full64", "-sverilog", "+delay_mode_distributed", "+notimingcheck", "-timescale=1ns/1ps",
             "+define+ARM_UD_MODEL+KWT_UNIFIED_GATE+DISABLE_SV_ASSERTION=1", "-debug_access+all",
             "+incdir+"+OUT.relative_to(ROOT).as_posix(), "-top", "complete_soc_tb",
             "-f", files, "-Mdir="+str(WORK/"csrc"), "-o", binary], WORK/"compile.log")
    return binary


def capture(binary, row, vcd=False):
    case = row["case"]
    label = "%02d" % case
    receipt = WORK / ("capture_"+label+".json")
    if receipt.exists() and (not vcd or read(receipt)["vcd"]):
        return read(receipt)
    log = WORK / ("run_"+label+".log")
    activity = WORK / ("activity_"+label+".saif")
    waveform = WORK / ("activity_"+label+".vcd")
    command = [binary, "+FIRST_TASK="+str(case), "+TASKS=1", "+RESULT_DIR="+str(RESULTS), "+SAIF="+str(activity)]
    if vcd:
        command.append("+VCD="+str(waveform))
    job(command, log)
    data = log.read_text()
    assert "UNIFIED_PUBLIC_ALL_PASS" in data
    for marker in MARKERS:
        line, = re.findall(r"(?m)^"+marker+r" (.*)$", data)
        counts = {key:int(value) for key,value in re.findall(r"(\w+)=(\d+)",line)}
        if marker == "THREEBANK_COUNTS":
            for key in ("reads", "writes", "acks", "last_commit", "last_ack"):
                assert counts[key] == row["counts"][key], (case, key, counts[key])
        else:
            assert counts["cycles"] == row["cycles"] and counts["outputs"] == 25344
            assert counts["checked_physical_addresses"] == 12672
    with activity.open() as stream:
        header = "".join(next(stream) for _ in range(16))
    begin, end, cycles = re.search(r"WIDE_CAPTURE_WINDOW start_ns=([.\d]+) end_ns=([.\d]+) cycles=(\d+)", data).groups()
    scale, unit = re.search(r"\(TIMESCALE\s+(\d+)\s+(ns|ps|fs)\)", header).groups()
    duration = Decimal(re.search(r"\(DURATION\s+([.\d]+)\)", header)[1]) * int(scale)
    duration *= dict(ns=Decimal(1), ps=Decimal("0.001"), fs=Decimal("0.000001"))[unit]
    assert abs(duration - (Decimal(end)-Decimal(begin))) < Decimal("0.01")
    assert int(cycles) == row["cycles"]
    assert not vcd or waveform.stat().st_size > 0
    result = dict(case=case, cycles=int(cycles), start_ns=begin, end_ns=end, duration_ns=str(duration),
                  saif=activity.relative_to(ROOT).as_posix(),
                  vcd=waveform.relative_to(ROOT).as_posix() if vcd else None)
    save(receipt, result)
    print("WIDE_GATE_ACTIVITY_PASS", case, cycles, activity.stat().st_size, flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", action="store_true")
    args = parser.parse_args()
    preflight()
    screen = read(REPORT/"final-screen.json")
    cpu = read(REPORT/"cpu-result.json")
    assert screen["timing_passed"] and cpu["passed_throughput"]
    binary = build(screen)
    captures = [capture(binary, cpu["cases"][0], vcd=True)]
    if not args.first:
        with ThreadPoolExecutor(max_workers=settings()["cpu_case_workers"]) as pool:
            captures += list(pool.map(lambda row: capture(binary,row), cpu["cases"][1:]))
        save(WORK/"captures.json", dict(variant=NAME, tag=screen["tag"], captures=captures))


if __name__ == "__main__":
    main()
