"""Read-only structural cost budget from accepted IR and the same frozen cell library."""
from pathlib import Path
import csv
import json
import re
from model import ROOT, REPORT


def main():
    base = ROOT / 'reports/server/complete_soc_sm40_opt_ffn_lp_IR_broadcast_v3_final_ss_ema2'
    lines = (base / 'area.rpt').read_text().splitlines()
    areas = {}
    for i, line in enumerate(lines[:-1]):
        if line.startswith('soc/'):
            values = re.findall(r'[-+]?\d+\.\d+', lines[i + 1])
            if len(values) >= 5:
                areas[line.strip()] = dict(total=float(values[0]), combinational=float(values[2]),
                                           sequential=float(values[3]), macros=float(values[4]))
    stem = 'soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller'
    known = {name: areas[stem + suffix] for name, suffix in [
        ('controller', ''), ('frontend', '/dma_frontend'), ('engine', '/dma_frontend/loading_dma'),
        ('core_arbiter', '/dma_frontend/core_arbiter'), ('output_queue', '/core/output_queue')]}
    cell_areas = {}
    source = ROOT / 'reports/optimization/ffn_logic_power/diagnosis/ffn_jp_HM2/private_leaf_power.tsv'
    with source.open() as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            cell_areas[row['ref_name']] = float(row['area_um2'])
    netlist = (ROOT / 'build/server/complete_soc_sm40_opt_ffn_lp_IR_broadcast_v3_final_ss_ema2/netlist.v').read_text()
    actual_refs = set(re.findall(r'^\s*(\w+)\s+(?:\\\S+|[\w$]+)\s*\(', netlist, re.M))
    samples = {ref: area for ref, area in cell_areas.items() if ref in actual_refs and
               (ref.startswith('DRNQV0') or ref.startswith('MUX2V0') or ref.startswith('CLKLANAQV1'))}
    with (base / 'power_1/area_power_macros.tsv').open() as stream:
        macros = [row for row in csv.DictReader(stream, delimiter='\t') if row['role'] in ['input', 'stash']]
    macro_area = float(macros[0]['area_um2'])
    for bank in range(3):
        cell = stem + '/core/output_queue/row_stash_%d__memory/macro_wrapper' % bank
        macros.append(dict(role='output', cell=cell + '/macro', ref_name='RAMSP128X16',
                           area_um2=areas[cell]['macros']))
    ff_ref = next((ref for ref in samples if ref.startswith('DRNQV0')), None)
    ff_area = samples.get(ff_ref)
    frontend_non_engine = known['frontend']['total'] - known['engine']['total']
    evidence = dict(
        source_area_report=str((base / 'area.rpt').relative_to(ROOT)),
        same_library_cell_area_source=str(source.relative_to(ROOT)),
        cell_area_usage='Geometry only from same frozen library; HM2 activity/power never substituted for IR',
        current_ir_hierarchy_um2=known,
        actual_ir_reference_samples_um2=samples,
        current_five_io_macros=[dict(role=row['role'], cell=row['cell'], ref_name=row['ref_name'], area_um2=float(row['area_um2'])) for row in macros],
        macro_source_note='Input entries use native macro TSV precision; three output entries use area.rpt macro-wrapper macro-area columns. No power attributed to output macros from the input-only TSV.',
        potentially_removable_upper_bounds_um2=dict(
            old_frontend_except_retained_dma_engine=frontend_non_engine,
            old_core_arbiter=known['core_arbiter']['total'],
            one_io_macro=macro_area),
        non_additive_budget_note='Core arbiter is already inside frontend-except-engine; never add both. Macro removal is unproven and gets no accepted savings credit.',
        retained=dict(dma_engine_um2=known['engine']['total'], fifo_items=16, macs=16),
        proposed_state_scales=dict(
            four_runtime_base_pointers_bits=128,
            four_runtime_base_pointers_bare_ff_um2=128 * ff_area if ff_area else None,
            naive_32_entry_bank_slot_valid_map_bits=192,
            naive_map_bare_ff_um2=192 * ff_area if ff_area else None,
            note='Reference FF scales, not final implementation estimates. Counters, tags, muxes, decode, gates, fanout repair and mapping feasibility remain unmeasured.'),
        accepted_area_savings_um2=0,
        added_mux_clock_and_timing_repair_um2=None,
        whole_soc_power_change_w=None,
        status='cost_coverage_not_demonstrated',
        decision='Do not issue an area/power-feasible hardware recommendation from these upper bounds alone')
    (REPORT / 'cost-budget.json').write_text(json.dumps(evidence, indent=2))
    rows = [
        ['Retained DMA engine', known['engine']['total'], 'Retained; no deletion credit'],
        ['Old frontend excluding DMA', frontend_non_engine, 'Maximum existing region; some function must remain'],
        ['Old arbiter, inside preceding row', known['core_arbiter']['total'], 'Overlapping subset; do not add twice'],
        ['One RAMSP128X16', macro_area, 'Removal not established by M3'],
        ['128 base-pointer FF bits', 128 * ff_area if ff_area else '', 'Bare FF reference, logic/repair excluded'],
        ['192 mapping FF bits', 192 * ff_area if ff_area else '', 'Naive dynamic map reference; tags/logic excluded']]
    with (REPORT / 'cost-budget.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['structure', 'area_um2', 'interpretation'])
        writer.writerows(rows)
    print(json.dumps(dict(status=evidence['status'], known=known, samples=samples,
                         frontend_non_engine_um2=frontend_non_engine, single_macro_um2=macro_area), indent=2))


if __name__ == '__main__':
    main()
