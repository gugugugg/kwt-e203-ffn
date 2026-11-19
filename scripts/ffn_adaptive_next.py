"""Immutable parents and manifests for exact row-input and weight reuse experiments."""
from pathlib import Path
import json
from ffn_adaptive import ROOT, copy_tree, dump, rank, features

REPORT = ROOT / 'reports/optimization/ffn_adaptive_next'
BUILD = ROOT / 'build/optimization/ffn_adaptive_next'
MANIFESTS = ROOT / 'constraints/ffn_adaptive_next/candidates'


def candidates():
    return {p.stem: json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}


def load(variant):
    return json.loads((MANIFESTS / (variant + '.json')).read_text())


def freeze():
    target = BUILD / 'frozen_adaptive'
    if (target / 'parents.json').exists():
        return json.loads((target / 'parents.json').read_text())
    previous = ROOT / 'reports/optimization/ffn_adaptive'
    delivered = previous / 'delivery-status.json'
    if not delivered.exists() or not json.loads(delivered.read_text()).get('complete'):
        return None
    selection = json.loads((previous / 'final-selection.json').read_text())
    if not selection.get('complete') or not selection.get('native_power_precision_refreshed'):
        return None
    decisions = json.loads((previous / 'dataflow-decisions.json').read_text())
    if any(decisions[k]['status'] not in ['measured', 'not_applicable'] for k in ['response', 'fifo']):
        return None
    dump(target / 'previous-selection.json', selection)
    dump(target / 'dataflow-decisions.json', decisions)
    chosen = dict(winner=selection['winner'],
                  eight=min((r for r in selection['ranking'] if not features(r)['lanes16']), key=rank),
                  sixteen=min((r for r in selection['ranking'] if features(r)['lanes16']), key=rank))
    parents = {}
    for family, row in chosen.items():
        name = row['variant']
        folder = target / name
        if not (folder / 'parent.json').exists():
            config = json.loads((ROOT / 'build/optimization/complete_soc' / name / 'configuration.json').read_text())
            copy_tree(ROOT / config['source_snapshot'], folder / 'rtl_sources')
            copy_tree(ROOT / config['firmware'], folder / 'firmware')
            changes = {}
            manifest = ROOT / 'constraints/ffn_adaptive/candidates' / (name + '.json')
            if manifest.exists():
                m = json.loads(manifest.read_text());changes = m.get('effective_changes', m['changes'])
            record = dict(variant=name, state=row, configuration=config, features=features(row),
                          effective_changes=changes, profile=json.loads((ROOT / row['profile']).read_text()),
                          source_snapshot=str((folder / 'rtl_sources').relative_to(ROOT)),
                          firmware=str((folder / 'firmware').relative_to(ROOT)))
            dump(folder / 'parent.json', record)
        parents[family] = json.loads((folder / 'parent.json').read_text())
    dump(target / 'parents.json', parents)
    return parents


def create(parent, family, label, purpose='experiment'):
    name = 'ffn_next_' + family + '_' + label
    changes = dict(row_cache=label in ['S', 'SR'], row_pair=label in ['R', 'SR'])
    manifest = dict(variant=name, parent_variant=parent['variant'], parent=parent,
                    features=dict(parent['features']), changes=changes,
                    effective_changes=dict(parent.get('effective_changes', {}), **changes),
                    purpose=purpose, numerical_package='models/kwt_unified_optimized_v1',
                    objective=['mean_task_energy', 'throughput', 'budget_area'])
    path = MANIFESTS / (name + '.json')
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise RuntimeError('Different frozen parent already recorded for ' + name)
    if not path.exists():dump(path, manifest)
    return name
