"""Read the sixth-round B comparison without changing its historical reports."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/optimization/ffn_area_power/power-comparison-review'


def reviewed_parent(row):
    directory = REPORT / row['variant']
    path = directory / 'result.json'
    result = json.loads(path.read_text())
    profile = json.loads((ROOT / row['profile']).read_text())
    if not result['passed'] or result['tag'] != profile['tag']:
        raise RuntimeError('Read the accepted same-netlist B power comparison: ' + str(path))
    tasks = sorted([task for p in (ROOT / 'reports/optimization/complete_soc' / row['variant']).glob('task_*.json')
                    for task in json.loads(p.read_text())['tasks']], key=lambda task: task['case'])
    module_energy = {}
    for task in tasks:
        groups = json.loads((directory / ('power_%d' % task['case']) / 'power_groups.json').read_text())
        for name, group in groups['groups'].items():
            energy = (group['internal_w'] + group['switching_w'] + group['leakage_w']) * task['cycles'] / 150000000 / 12
            module_energy[name] = module_energy.get(name, 0) + energy
    return dict(row, metrics=dict(row['metrics'], power_reports=result['power_reports']),
                mean_energy_j=result['mean_energy_j'], mean_power_w=result['mean_power_w'],
                throughput_per_second=result['throughput_per_second'], module_mean_energy_j=module_energy,
                power_phase_review=path.relative_to(ROOT).as_posix())
