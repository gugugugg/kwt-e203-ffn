"""Round-three candidates, all relative to the accepted MWQPF implementation."""
from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
BASE = 'ffn_v2_MWQPF'
FEATURES = {
    'N': 'split_bias', 'U': 'unroll', 'I': 'fast_pair',
    'T': 'overlap', 'G': 'clock_gating', 'L': 'lanes16'}
NAMES = ['N', 'U', 'I', 'NT', 'G', 'NL', 'NUI', 'NUIT', 'NUIG',
         'NUIL', 'NUITG', 'NUITL', 'NUIGL', 'NUITGL']
CANDIDATES = {'ffn_v3_' + name: {key: letter in name for letter, key in FEATURES.items()}
              for name in NAMES}


def copy_tree(source, destination):
    """Copy owned snapshots with the server's Python 3.6 runtime."""
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob('*'):
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def freeze():
    out = ROOT / 'build/optimization/ffn_round3/frozen_baseline'
    if (out / 'baseline.json').exists():
        return out
    out.mkdir(parents=True, exist_ok=True)
    selected = json.loads((ROOT / 'constraints/ffn_selected.json').read_text())
    if selected['variant'] != BASE:
        raise RuntimeError('Round three requires the accepted MWQPF baseline')
    for field, target in [('source_snapshot', 'rtl_sources'), ('firmware', 'firmware')]:
        copy_tree(ROOT / selected[field], out / target)
    for source, target in [('constraints/ffn_selected.json', 'selected.json'),
                           ('reports/optimization/ffn_round2/final-selection.json', 'round2-selection.json'),
                           ('reports/optimization/ffn_round2/accumulator-proof.json', 'accumulator-proof.json')]:
        shutil.copy2(ROOT / source, out / target)
    (out / 'baseline.json').write_text(json.dumps({
        'variant': BASE, 'selection': selected, 'candidate_features': CANDIDATES,
        'source_policy': 'reuse accepted baseline; do not rematerialize round-two sources',
        'objective': ['mean_task_energy', 'throughput', 'budget_area']}, indent=2))
    return out


if __name__ == '__main__':
    print(freeze())
