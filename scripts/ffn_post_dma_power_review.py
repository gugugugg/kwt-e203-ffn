"""Use corrected same-netlist parent power without altering historical acceptance files."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/optimization/ffn_post_dma/power-comparison-review'
PARENTS = ['ffn_ld_D1', 'ffn_ld_D2', 'ffn_ld_T_D1', 'ffn_ld_T_D2']


def reviewed(row):
    if row['variant'] not in PARENTS:
        return row
    path = REPORT / row['variant'] / 'result.json'
    result = json.loads(path.read_text())
    profile = json.loads((ROOT / row['profile']).read_text())
    if not result['passed'] or result['tag'] != profile['tag']:
        raise RuntimeError('Inspect corrected parent power comparison: ' + str(path))
    metrics = dict(row['metrics'], power_reports=result['power_reports'])
    return dict(row, metrics=metrics, mean_energy_j=result['mean_energy_j'],
                mean_power_w=result['mean_power_w'], module_mean_energy_j=result['module_mean_energy_j'],
                throughput_per_second=result['throughput_per_second'],
                power_phase_review=str(path.relative_to(ROOT)).replace('\\', '/'))


def parent_rows(parents):
    rows = {p['variant']: p['state'] for p in parents.values()}
    return [reviewed(rows[name]) for name in PARENTS]
