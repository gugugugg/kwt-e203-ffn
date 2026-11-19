"""Measure twelve cold-task SAIFs and one mapped task on the audited final."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from native import ROOT, NAME, REPORT, OUT, read, save, preflight
import mapped
import native_power


def power_script():
    source=OUT/"eda/power.tcl"
    original=source.read_text()
    groups=(ROOT/"scripts/server/export_ffn_area_power_groups.tcl").read_text()
    groups=groups.replace(
        '([string match *scratch* $name] || [string match *ap_input_rows* $name])',
        '[string match *core*input_memory* $name]')
    groups=groups.replace(
        '[string match *parameter_banks*weights* $name]',
        '[string match *core*weight_columns* $name]')
    groups=groups.replace(
        '[string match *core*accumulator* $name]',
        '([string match *core*acc_a_reg* $name] || [string match *core*acc_b_reg* $name])')
    groups=groups.replace('[string match *row_stash*', '[string match *core*result_memory*')

    (OUT/"eda/threebank_power_groups.tcl").write_text(groups)
    replacements={
        'source scripts/server/export_ffn_area_power_groups.tcl':
            'source '+(OUT/"eda/threebank_power_groups.tcl").relative_to(ROOT).as_posix(),
        'source build/optimization/complete_soc/'+NAME+'/eda/q8_leaf_power.tcl\n':'',
        'source scripts/server/export_ffn_area_power_evidence.tcl\nap_export_evidence $report\n':'',
        'source scripts/server/export_ffn_ar_area_evidence.tcl\n':'',
    }
    for old,new in replacements.items():
        original=original.replace(old,new)
    source.write_text(original)


def main():
    preflight()
    screen=read(REPORT/"final-screen.json")
    cpu=read(REPORT/"cpu-result.json")
    proof=read(REPORT/"acceptance-handoff.json")
    phase=read(REPORT/"phase-verdict.json")
    assert screen["timing_passed"] and screen["area_passed"]
    assert screen["tag"]==proof["tag"]==phase["tag"]
    assert all(proof["proofs"].values()) and phase["passed"]
    audit=REPORT/"activity-mapping/native-review-next"/NAME
    correction=audit/"reviewed-draft"/(NAME+".tcl")
    probe=audit/phase["attempt"]
    assert correction.read_bytes()==(probe/"correction-used.tcl").read_bytes()
    (REPORT/"activity-mapping"/(NAME+".tcl")).write_bytes(correction.read_bytes())
    power_script()
    with ThreadPoolExecutor(max_workers=2) as pool:
        gate=pool.submit(mapped.run,screen,cpu,read(audit/"mapped-expressions.json"))
        measurement=native_power.power(NAME,REPORT,OUT,screen,cpu,probe)
        gate.result()
    area=screen["area"]["accelerator_budget_including_shared_interface_mm2"]
    energy=measurement["mean_energy_j"]
    acceptance=cpu["passed_throughput"] and area<=0.4 and energy<=6.764e-6
    save(REPORT/"research-verdict.json",dict(variant=NAME,accepted=acceptance,
         same_netlist_150mhz=True,area_mm2=area,area_minus_0300_mm2=area-0.300,
         throughput=measurement["throughput"],mean_power_w=measurement["mean_power_w"],
         mean_energy_j=energy,energy_minus_target_j=energy-6.764e-6,publication_changed=False))


if __name__=="__main__":
    main()


