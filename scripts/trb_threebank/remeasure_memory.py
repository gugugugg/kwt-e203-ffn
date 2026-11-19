"""Remeasure the accepted checkpoint with the recorded private macro Q activity."""
from concurrent.futures import ThreadPoolExecutor
from collections import Counter, defaultdict
import os
import struct
import sys

from native import ROOT, NAME, REPORT, OUT, DEST, job, preflight, read, save, settings
from observe_memory import EVIDENCE
from sr_area.review_normal_power import records

FIELDS = ("internal_w", "switching_w", "leakage_w", "total_w")


def f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def prepare(mapping):
    original = (OUT / "eda/power.tcl").read_text()
    old_report = "/power_$env(XPIAN_TASK)"
    map_source = "source reports/optimization/{}/activity-mapping/{}.tcl".format(NAME, NAME)
    assert original.count(old_report) == original.count(map_source) == 1
    extra = EVIDENCE / "private-q-overlay.tcl"
    rules = ["set_rtl_to_gate_name -rtl {%s} -gate {%s}" % (row["rtl"], row["gate"])
             for row in mapping]
    extra.write_text("\n".join(rules) + "\n")
    native_report = """
set private_q_file [open $report/private-memory-Q-activity.rpt w]
foreach pin {%s} {
    set pins [get_pins $pin]
    set net [get_nets -of_objects $pins]
    puts $private_q_file "NET [get_object_name $net]"
    puts $private_q_file "SP [get_switching_activity -static_probability $net]"
    puts $private_q_file "TR [get_switching_activity -toggle_rate $net]"
}
close $private_q_file
""" % " ".join("{%s}" % row["pin"] for row in mapping)
    marker = "ffn_report_reviewed_activity $report"
    assert original.count(marker) == 1
    script = OUT / "eda/power_observed_memory.tcl"
    script.write_text(original.replace(old_report, "/power_observed_$env(XPIAN_TASK)").replace(
        map_source, map_source + "\nsource " + extra.relative_to(ROOT).as_posix()).replace(
        marker, marker + "\n" + native_report))
    return script


def verify(case, evidence, report, mapping, previous):
    activity = records(report / "private-memory-Q-activity.rpt")
    assert len(activity) == len(mapping)
    errors = []
    sources = Counter()
    for index, actual in enumerate(activity):
        assert actual["net"] == mapping[index]["gate"]
        raw = evidence["values"][str(index)]
        known = raw["T0"] + raw["T1"]
        sources.update(actual[k]["source"] for k in ("SP", "TR"))
        if known:
            expected = dict(SP=format(f32(raw["T1"] / known), ".6g"),
                            TR=format(f32(f32(raw["TC"]) / f32(evidence["duration_ns"])), ".6g"))
            for field, value in expected.items():
                if actual[field]["source"] != "file" or actual[field]["value"] != value:
                    errors.append(dict(index=index, field=field, expected=value, actual=actual[field], raw=raw))
        else:
            errors.append(dict(index=index, actual=actual, reason="No known Q state in the whole cold window"))
    before = records(previous / "activity-phase-review.rpt")
    after = records(report / "activity-phase-review.rpt")
    assert [x["net"] for x in before] == [x["net"] for x in after]
    preserved = 0
    for old, new in zip(before, after):
        for key in ("SP", "TR"):
            if old[key]["source"] == "file":
                if old[key] != new[key]:
                    errors.append(dict(net=old["net"], field=key, previous=old[key], actual=new[key]))
                else:
                    preserved += 1
    result = dict(case=case, passed=not errors, q_activity_sources=dict(sources),
                  preserved_prior_file_attributes=preserved, differences=errors)
    save(report / "private-memory-Q-verdict.json", result)
    if errors:
        raise RuntimeError("Read private Q activity verdict for case " + str(case))
    return result


def main():
    preflight()
    screen = read(REPORT / "final-screen.json")
    cpu = read(REPORT / "cpu-result.json")
    proof = read(REPORT / "acceptance-handoff.json")
    phase = read(REPORT / "phase-verdict.json")
    mapped = read(DEST / "mapped_evaluation.json")
    assert mapped["passed"] and screen["timing_passed"] and screen["area_passed"]
    assert screen["tag"] == proof["tag"] == phase["tag"] == mapped["tag"]
    assert all(proof["proofs"].values()) and phase["passed"]
    mapping = read(EVIDENCE / "memory-observed-q-map.json")
    script = prepare(mapping)
    folder = ROOT / "reports/server" / ("complete_soc_sm40_" + screen["tag"])

    def run(case):
        number = case["case"]
        evidence = read(EVIDENCE / ("case_%02d.json" % number))
        report = folder / ("power_observed_%d" % number)
        previous = folder / ("power_%d" % number)
        log = EVIDENCE / ("power_%02d.log" % number)
        if not (log.is_file() and "XPIAN_ENCODER_POWER_DONE" in log.read_text() and
                (report / "power_values.json").is_file() and
                (report / "private-memory-Q-activity.rpt").is_file()):
            env = dict(os.environ, XPIAN_TAG=screen["tag"], XPIAN_CORNER="ss", XPIAN_TASK=str(number),
                       XPIAN_ACTIVITY=evidence["merged_saif"])
            job(["pt_shell", "-f", script], log, env)
        assert "XPIAN_ENCODER_POWER_DONE" in log.read_text() and "XPIAN_POWER_PRECISE_EXPORT=1" in log.read_text()
        verify(number, evidence, report, mapping, previous)
        power = read(report / "power_values.json")
        old = read(previous / "power_values.json")
        groups = read(report / "power_groups.json")
        assert power["unit"] == old["unit"] == groups["unit"] == "W"
        print("THREEBANK_OBSERVED_POWER", number, power["total_w"], old["total_w"], flush=True)
        return dict(case=number, cycles=case["cycles"], old_default_power_w=old["total_w"],
                    groups=groups["groups"], **{key:power[key] for key in FIELDS})

    first = run(cpu["cases"][0])
    if sys.argv[1] == "first":
        return
    with ThreadPoolExecutor(max_workers=settings()["power_case_workers_per_candidate"]) as pool:
        rows = [first] + list(pool.map(run, cpu["cases"][1:]))
    total = cpu["cycles_total"]
    clock = cpu["clock_hz"]
    assert len(rows) == 12 and sum(row["cycles"] for row in rows) == total
    sums = {key:sum(row[key]*row["cycles"] for row in rows) for key in FIELDS}
    components = defaultdict(float)
    for row in rows:
        for group, values in row["groups"].items():
            components[group] += row["cycles"] * sum(values[key] for key in FIELDS[:-1])
    groups = {key:dict(mean_power_w=value/total, mean_energy_j=value/(12*clock))
              for key, value in sorted(components.items())}
    power = sums["total_w"] / total
    energy = sums["total_w"] / (12*clock)
    throughput = 12*clock / total
    area = screen["area"]["accelerator_budget_including_shared_interface_mm2"]
    acceptance = total <= 339622 and area < 0.387089831
    save(REPORT / "power-result.json", dict(variant=NAME, tag=screen["tag"], clock_hz=clock,
         cycles_total=total, throughput=throughput, mean_power_w=power, mean_energy_j=energy,
         weighted_power={key:value/total for key,value in sums.items()}, weighted_leaf_groups=groups,
         original_default_mean_power_w=sum(row["old_default_power_w"]*row["cycles"] for row in rows)/total,
         all_cases_private_q_verified=True, measured_private_q_bits=384, measurements=rows))
    save(REPORT / "research-verdict.json", dict(variant=NAME, accepted=acceptance,
         same_netlist_150mhz=True, mapped_passed=True, proofs=proof["proofs"], area_mm2=area,
         area_minus_0300_mm2=area-0.300, throughput=throughput, cycles_total=total,
         mean_power_w=power, mean_energy_j=energy, energy_minus_8uj_j=energy-8e-6,
         energy_below_baseline=energy<9.987547185355438e-6, matched_8uj=energy<=8e-6,
         publication_changed=False))
    print("THREEBANK_POWER_COMPLETE", power, energy, throughput, area, flush=True)


if __name__ == "__main__":
    main()

