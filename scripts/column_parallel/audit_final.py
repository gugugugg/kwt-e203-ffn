"""Reconcile the accepted native measurements and unchanged publication after delivery."""
from pathlib import Path
import json
import math
import sys
from prepare import ROOT, REPORT, BUILD


def main():
    selection = json.loads((REPORT/'final-selection.json').read_text())
    row = selection['candidate']
    parent = selection['baseline']
    profile = json.loads((ROOT/row['profile']).read_text())
    tag = profile['tag']
    folder = ROOT/'reports/optimization/complete_soc/ffn_cp_C16'
    tasks = sorted([t for p in folder.glob('task_*.json') for t in json.loads(p.read_text())['tasks']], key=lambda t: t['case'])
    evaluation = json.loads((folder/'power_evaluation.json').read_text())
    if len(tasks) != 12 or len(evaluation) != 12 or not all(p['completed'] and not p['reused_initial_measurement'] and p['tag'] == tag for p in evaluation):
        raise RuntimeError('Read this candidate CPU12 and own fresh power12')
    if not all(t['cycles'] == 100567 and t['outputs'] == 25344 and t['trace'] == 25344 for t in tasks):
        raise RuntimeError('CPU task/output/ordered-trace results differ')
    if not all(row.get(k) for k in ['formal_passed', 'mapped_passed', 'rtl_formal_passed', 'hold_repair_formal_passed', 'final_repair_formal_passed']):
        raise RuntimeError('Read own mapped/formal acceptance flags')
    assessment = row['assessment_clock_gating']
    if not assessment['passed'] or assessment['tag'] != tag:
        raise RuntimeError('Final checkpoint timing assessment differs')
    energy = 0.0
    for task in tasks:
        power = json.loads((ROOT/'reports/server'/('complete_soc_sm40_'+tag)/('power_%d' % task['case'])/'power_values.json').read_text())
        if power['unit'] != 'W':
            raise RuntimeError('Native power units differ')
        energy += power['total_w']*task['cycles']/150000000
    cycles = sum(t['cycles'] for t in tasks)
    measured = dict(mean_energy_j=energy/12, mean_power_w=energy/(cycles/150000000), throughput_per_second=12*150000000/cycles)
    if any(measured[k] != row[k] for k in measured):
        raise RuntimeError('Exact final aggregation differs')
    if (ROOT/'constraints/ffn_selected.json').read_bytes() != (BUILD/'frozen/selected-original.json').read_bytes():
        raise RuntimeError('IR publication bytes changed')
    mapped = json.loads((folder/'mapped_evaluation.json').read_text())
    if len(mapped) != 1 or not mapped[0]['passed'] or mapped[0]['case'] != 1:
        raise RuntimeError('Representative real CPU mapped result is incomplete')
    area_key = 'accelerator_budget_including_shared_interface_mm2'
    area = row['metrics']['area'][area_key]
    old_area = parent['metrics']['area'][area_key]
    limits = selection['targets']
    objective = (measured['mean_energy_j'] < limits['energy_strictly_below_j'] and
                 measured['throughput_per_second'] >= limits['throughput_at_least'] and
                 area <= limits['area_at_most_mm2'])
    if objective != selection['target_met']:
        raise RuntimeError('Exact target decision differs')
    result = dict(passed=True, variant='ffn_cp_C16', tag=tag, CPU12=True, fresh_power12=True,
                  complete_three_proofs=True, representative_mapped=True,
                  mapped_trace_is_not_ordered_trace=True, same_final_SS150_gating_electrical=True,
                  publication='ffn_lp_IR', publication_changed=False, objective_met=objective,
                  area_mm2=area, **measured)
    result['relative_to_IR_percent'] = dict(
        energy=100*(row['mean_energy_j']/parent['mean_energy_j']-1),
        throughput=100*(row['throughput_per_second']/parent['throughput_per_second']-1),
        power=100*(row['mean_power_w']/parent['mean_power_w']-1), area=100*(area/old_area-1))
    (REPORT/'final-acceptance-audit.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
