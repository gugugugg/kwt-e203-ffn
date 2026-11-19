"""Frozen published C16 and the sole model-selected efficiency experiment."""
from pathlib import Path
import json
import shutil
from ffn_residual import prove_bias32, prove_zero_schedule

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT/'reports/optimization/ffn_c16_efficiency'
BUILD = ROOT/'build/optimization/ffn_c16_efficiency'
MANIFESTS = ROOT/'constraints/ffn_c16_efficiency/candidates'
AREA_LIMIT = 0.2764843225
ENERGY_LIMIT_J = 1.8435083907942435e-05
THROUGHPUT_MIN = 1000


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))


def load(name):
    return json.loads((MANIFESTS/(name+'.json')).read_text())


def candidates():
    return {'ffn_ce_W':load('ffn_ce_W')}


def review_group(name):
    return 'W'


def copy_tree(source, destination):
    for path in source.rglob('*'):
        if path.is_file():
            target = destination/path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(path), str(target))


def same_rtl(name, manifest):
    raise ValueError('C16 is new hardware and requires its own CPU, mapping, power and proofs')


def feasible(row):
    return (row.get('formal_passed') is True and row['throughput_per_second'] >= THROUGHPUT_MIN and
            row['mean_energy_j'] < ENERGY_LIMIT_J and
            row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'] <= AREA_LIMIT)
