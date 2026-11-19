"""Compare same-final-netlist SAIF and VCD in PrimeTime PX averaged mode."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import gzip
import os
import re

from native import NAME, OUT, REPORT, ROOT, job, preflight, read, save, settings

CAPTURE = REPORT / "gate-activity"
POWER = REPORT / "gate-power"
FIELDS = ("internal_w", "switching_w", "leakage_w", "total_w")
NS = {"fs": Decimal("0.000001"), "ps": Decimal("0.001"), "ns": Decimal(1)}


def vcd_window(case):
    original = ROOT / case["vcd"]
    clipped = POWER / "case01_cold.vcd.gz"
    receipt = POWER / "vcd-window.json"
    if clipped.is_file() and receipt.is_file():
        return clipped
    start_ns, end_ns = Decimal(case["start_ns"]), Decimal(case["end_ns"])
    saif_duration = Decimal(case["duration_ns"])
    saif_quantum = Decimal(1).scaleb(saif_duration.as_tuple().exponent)
    temporary = clipped.with_suffix(".tmp")
    with original.open("rb") as source, gzip.open(str(temporary), "wb", compresslevel=1) as target:
        header = []
        for line in source:
            header.append(line)
            if b"$enddefinitions" in line:
                break
        scale, unit = re.search(rb"\$timescale\s+(\d+)\s*(fs|ps|ns)\s*\$end",
                                b"".join(header)).groups()
        tick = int(scale) * NS[unit.decode()]
        start, end = (int((ns/tick).to_integral_value()) for ns in (start_ns,end_ns))
        target.writelines(header)
        first = None
        last = None
        remainder = b""
        while last is None:
            block = source.read(8 * 1024 * 1024)
            if not block:
                break
            lines, _, remainder = (remainder + block).rpartition(b"\n")
            if not lines:
                continue
            lines += b"\n"
            cursor = 0
            for marker in re.finditer(rb"(?m)^#(\d+)\r?\n", lines):
                now = int(marker[1])
                if first is not None:
                    target.write(lines[cursor:marker.start()])
                elif lines[cursor:marker.start()].strip():
                    raise ValueError("VCD has initial values before the first dump timestamp")
                if now >= end:
                    last = now
                    break
                if first is None:
                    first = now
                    if abs((now-start)*tick) > tick:
                        raise ValueError("VCD first dump does not match the cold start")
                target.write(("#%d\n" % (now-first)).encode())
                cursor = marker.end()
            if last is None and first is not None:
                target.write(lines[cursor:])
        if first is None or last is None or abs((end-first)*tick-saif_duration) > max(2*tick, saif_quantum):
            raise ValueError("VCD does not span the same cold window as the gate SAIF")
        target.write(("#%d\n" % (end-first)).encode())
    temporary.replace(clipped)
    save(receipt, dict(original=case["vcd"], timescale_ns=str(tick), first_dump_tick=first,
                       start_tick=start, end_tick=end, first_excluded_tick=last,
                       duration_ns=str((end-first)*tick), saif_duration_ns=str(saif_duration),
                       duration_difference_ns=str((end-first)*tick-saif_duration)))
    return clipped


def build_tcl():
    text = (OUT/"eda/power.tcl").read_text()
    prefix, suffix = text.split("\nupdate_timing\n", 1)
    assert "power_analysis_mode averaged" in prefix and "constraints/complete_soc.sdc" in prefix
    assert "saif_map" not in prefix and "read_verilog" in prefix
    prefix, count = re.subn(r"(?m)^set report .+$", "set report $env(XPIAN_POWER_REPORT)", prefix)
    assert count == 1
    body = r'''
update_timing
if {$env(XPIAN_ACTIVITY_FORMAT) eq "SAIF"} {
    if {![read_saif -strip_path complete_soc_tb/dut $env(XPIAN_ACTIVITY)]} {
        error "Gate SAIF annotation failed"
    }
} else {
    read_vcd -strip_path complete_soc_tb/dut $env(XPIAN_ACTIVITY)
}
update_power
redirect $report/power.rpt {report_power -verbose -hierarchy}
source scripts/server/export_optimization_power.tcl
redirect $report/annotation.rpt {report_switching_activity}
redirect $report/unannotated.rpt {report_switching_activity -list_not_annotated}
set stream [open $report/private-macro-activity.rpt w]
foreach_in_collection macro [get_cells -hierarchical -quiet -filter {ref_name =~ RAMSP*}] {
    set name [get_object_name $macro]
    if {![string match */core/* $name]} {continue}
    set pins [get_pins -quiet -of_objects $macro -filter {direction == out}]
    foreach_in_collection pin $pins {
        set net [get_attribute -quiet $pin net]
        puts $stream "PIN [get_object_name $pin]"
        if {[sizeof_collection $net] == 0} {
            puts $stream "NO_NET"
            continue
        }
        redirect -variable probability {get_switching_activity -static_probability $net}
        redirect -variable toggle {get_switching_activity -toggle_rate $net}
        puts $stream $probability
        puts $stream $toggle
    }
}
close $stream
puts "XPIAN_WIDE_GATE_POWER_DONE $env(XPIAN_ACTIVITY_FORMAT) $env(XPIAN_ACTIVITY)"
exit
'''
    script = POWER / "gate_power.tcl"
    script.write_text(prefix + "\n" + body)
    return script


def measure(script, tag, row, fmt, activity):
    folder = POWER / ("%s_%02d" % (fmt.lower(), row["case"]))
    folder.mkdir(exist_ok=True)
    done = folder / "measurement.json"
    if done.exists():
        return read(done)
    log = folder / "pt.log"
    output = folder / "power_values.json"
    env = dict(os.environ, XPIAN_CORNER="ss", XPIAN_TAG=tag, XPIAN_TASK=str(row["case"]),
               XPIAN_POWER_REPORT=str(folder), XPIAN_ACTIVITY_FORMAT=fmt, XPIAN_ACTIVITY=str(activity))
    job(["pt_shell", "-f", script], log, env)
    assert "XPIAN_WIDE_GATE_POWER_DONE" in log.read_text()
    values = read(output)
    assert values["unit"] == "W" and values["total_w"] > 0
    macro_activity = (folder / "private-macro-activity.rpt").read_text()
    macro_q_count = len(re.findall(r"(?m)^PIN ", macro_activity))
    result = dict(case=row["case"], cycles=row["cycles"], tag=tag, activity_format=fmt,
                  private_macro_q_count=macro_q_count,
                  private_macro_q_without_net=macro_activity.count("NO_NET"),
                  activity=activity.relative_to(ROOT).as_posix(), **{f:values[f] for f in FIELDS})
    save(done, result)
    print("WIDE_GATE_POWER_PASS", fmt, row["case"], values["total_w"], flush=True)
    return result


def main():
    preflight()
    screen = read(REPORT/"final-screen.json")
    cpu = read(REPORT/"cpu-result.json")
    evidence = read(CAPTURE/"captures.json")
    captures = evidence["captures"]
    tag = screen["tag"]
    assert screen["timing_passed"] and evidence["tag"] == tag
    assert [(r["case"],r["cycles"]) for r in captures] == [(r["case"],r["cycles"]) for r in cpu["cases"]]
    assert len(captures) == 12 and cpu["clock_hz"] == 150000000
    POWER.mkdir(exist_ok=True)
    script = build_tcl()
    vcd = vcd_window(captures[0])
    tasks = [(r, "SAIF", ROOT/r["saif"]) for r in captures]
    tasks.insert(1, (captures[0], "VCD", vcd))
    with ThreadPoolExecutor(max_workers=settings()["power_case_workers_per_candidate"]) as pool:
        all_rows = list(pool.map(lambda args:measure(script, tag, *args), tasks))
    rows = [r for r in all_rows if r["activity_format"] == "SAIF"]
    case1_saif, case1_vcd = all_rows[:2]
    cycles = sum(r["cycles"] for r in rows)
    assert cpu["cycles_total"] == cycles
    clock = cpu["clock_hz"]
    area = screen["area"]["accelerator_budget_including_shared_interface_mm2"]
    totals = {f:sum(r[f]*r["cycles"] for r in rows) for f in FIELDS}
    power = {f:totals[f]/cycles for f in FIELDS}
    energy = totals["total_w"]/(len(rows)*clock)
    save(POWER/"result.json", dict(
        variant=NAME, tag=tag, clock_hz=clock, cycles_total=cycles, tasks=len(rows),
        throughput_per_second=len(rows)*clock/cycles, area_mm2=area, area_passed=area<=0.5,
        same_final_netlist_timing_passed=True, vcd_saif_same_gate_replay=True,
        activity_simulation="distributed library delays without SDF backannotation",
        mean_power_w=power["total_w"], mean_energy_j=energy, energy_passed=energy<=4e-6,
        weighted_power=power, measurements=rows, case1_saif=case1_saif, case1_vcd=case1_vcd,
        case1_saif_energy_j=case1_saif["total_w"]*case1_saif["cycles"]/clock,
        case1_vcd_energy_j=case1_vcd["total_w"]*case1_vcd["cycles"]/clock,
        case1_vcd_delta_percent=100*(case1_vcd["total_w"]/case1_saif["total_w"]-1),
        publication_changed=False))


if __name__ == "__main__":
    main()

