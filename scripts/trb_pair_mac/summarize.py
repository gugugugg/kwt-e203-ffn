"""Assemble measured pilot deltas and the bounded full-design screening verdict."""
import csv
import json
import re

from common import REPORT, ROOT, WORK, write_json

NATIVE = REPORT/"received"/"screen"/"native-evidence"
ROLES = ("shared","input","weight","result")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def macro_roles():
    modes = {}
    for mode in ("plain","gated"):
        path = NATIVE/WORK.relative_to(ROOT)/"macro_pilot"/mode/"leaf.tsv"
        roles = {role: {"count":0,"cell_power_w":0.0,"cell_area_um2":0.0} for role in ROLES}
        with path.open(encoding="utf-8") as stream:
            for leaf in csv.DictReader(stream, delimiter="\t"):
                name = leaf["name"]
                match = re.match(r"(?:gate_)?mem_(shared|input|weight|result)_",name)
                if match:
                    role = roles[match[1]]
                    role["count"] += 1
                    role["cell_power_w"] += float(leaf["power_w"])
                    role["cell_area_um2"] += float(leaf["area"])
        modes[mode] = roles
    return modes


def main():
    native = NATIVE/REPORT.relative_to(ROOT)
    model = read(REPORT/"model-result.json")
    macro = read(native/"macro-result.json")
    slices = read(native/"slice-result.json")["results"]
    isolated = read(native/"slice-isolated-result.json")["results"]["paired-isolated"]
    correction = read(native/"correction-result.json")
    vectors = read(native/"macro-replay-input.json")
    assert sum(vectors["known_read_checks"].values()) == 312390
    assert correction["checked_rows"] == 792 and correction["checked_bias_pairs"] == 3200

    old_power = read(ROOT/"reports/optimization/ffn_trb_128mac/received/gate-power/native-evidence/reports/optimization/ffn_trb_128mac/gate-power/result.json")
    paired_cycles = model["results"]["paired"]["cycles"]/12
    clock = old_power["clock_hz"]
    target_power = 4e-6*clock/paired_cycles
    gate_reduction = macro["plain"]["total_w"] - macro["gated"]["total_w"]
    pair_reduction = slices["plain"]["total_w"] - isolated["total_w"]
    approx_without_added_correction = old_power["mean_power_w"] - gate_reduction - 16*pair_reduction
    correction_hold_met = correction["hold_slack_ns"] is not None and correction["hold_slack_ns"] >= 0
    energy_estimate_within_target = approx_without_added_correction <= target_power
    result = dict(
        release=read(ROOT/"constraints/ffn_selected.json")["variant"],
        screening_decision="budget_not_supported" if not (energy_estimate_within_target and correction_hold_met)
                           else "full_area_and_energy_accounting_required",
        generated_whole_soc_candidate=False,
        cold_cycles=paired_cycles, throughput_model=model["results"]["paired"]["throughput"],
        baseline_mean_energy_j=old_power["mean_energy_j"],
        baseline_area_mm2=old_power["area_mm2"], timing_model_passed=model["passes_cycles"],
        macro_replay=macro, macro_cell_groups=macro_roles(), macro_reduction_w=gate_reduction,
        macro_replay_input=vectors, reference_slice=slices["plain"],
        paired_initial_slice=slices["paired"], paired_isolated_slice=isolated,
        correction_pilot=correction, target_mean_power_w=target_power,
        required_compute_reduction_after_macro_w=old_power["mean_power_w"]-gate_reduction-target_power,
        measured_compute_reduction_per_two_columns_w=pair_reduction,
        approximate_without_added_correction_power_w=approx_without_added_correction,
        approximate_without_added_correction_energy_j=approx_without_added_correction*paired_cycles/clock,
        projection_scope="case-one per-pilot deltas expanded as 16 two-column slices against frozen baseline mean; not a calibrated SoC power forecast; shared structures do not scale this way exactly",
        energy_estimate_within_target=energy_estimate_within_target,
        correction_hold_met=correction_hold_met,
    )
    assert result["release"]=="ffn_sg_reuse"
    write_json(REPORT/"screening-result.json",result)
    print("PAIR_SCREEN_SUMMARY",result["approximate_without_added_correction_energy_j"],
          result["required_compute_reduction_after_macro_w"])


if __name__ == "__main__":
    main()

