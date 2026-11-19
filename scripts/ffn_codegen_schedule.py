"""Frozen inputs and independent compiler/scheduler experiments."""
from pathlib import Path
import json
from ffn_adaptive import ROOT, copy_tree, dump, rank, features
from ffn_residual import prove_bias32, prove_zero_schedule

REPORT = ROOT / 'reports/optimization/ffn_codegen_schedule'
BUILD = ROOT / 'build/optimization/ffn_codegen_schedule'
MANIFESTS = ROOT / 'constraints/ffn_codegen_schedule/candidates'
SUPPORT = ['software/cpu_integration/startup.S', 'software/unified_cpu/main.c',
           'software/unified/kwt_unified_driver.h', 'software/cpu_integration/kwt_platform_addresses.h',
           'software/cpu_integration/link.ld']


def candidates():
    return {p.stem: json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}


def load(name):
    return json.loads((MANIFESTS / (name + '.json')).read_text())


def compiler(opt='O2', lto=False, gc=False):
    return dict(optimization=opt, lto=bool(lto), gc_sections=bool(gc))


def snapshot(row, folder, effective=None):
    path = folder / 'parent.json'
    if path.exists():
        return json.loads(path.read_text())
    config = json.loads((ROOT / 'build/optimization/complete_soc' / row['variant'] / 'configuration.json').read_text())
    copy_tree(ROOT / config['source_snapshot'], folder / 'rtl_sources')
    copy_tree(ROOT / config['firmware'], folder / 'firmware')
    for name in SUPPORT:
        target = folder / 'program' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((BUILD / 'program_support' / name).read_bytes())
    for name in ['driver.c', 'kernels.S']:
        source = folder / 'firmware' / name
        if source.exists():
            target = folder / 'program' / name
            target.write_bytes(source.read_bytes())
    saved_inputs = folder / 'firmware/input-files'
    if saved_inputs.exists():
        copy_tree(saved_inputs, folder / 'program')
    record = dict(variant=row['variant'], state=row, configuration=config,
                  features=features(row), effective_changes=effective or {},
                  profile=json.loads((ROOT / row['profile']).read_text()),
                  source_snapshot=(folder / 'rtl_sources').relative_to(ROOT).as_posix(),
                  firmware=(folder / 'firmware').relative_to(ROOT).as_posix(),
                  program=(folder / 'program').relative_to(ROOT).as_posix())
    if row['variant'].startswith('ffn_cg_'):
        prior = load(row['variant'])
        record['compiler'] = prior['compiler']
    else:
        record['compiler'] = compiler()
    dump(path, record)
    return record


def freeze():
    path = BUILD / 'frozen/parents.json'
    if path.exists():
        return json.loads(path.read_text())
    prior = ROOT / 'reports/optimization/ffn_transport'
    required = [prior / x for x in ['delivery-status.json', 'final-selection.json', 'local-sync-confirmed.json']]
    if not all(p.exists() for p in required):
        return None
    delivery, selection, ack = [json.loads(p.read_text()) for p in required]
    if not delivery.get('complete') or not selection.get('complete') or not selection.get('native_power_precision_refreshed'):
        return None
    winner = selection['winner']
    if ack.get('winner') != winner['variant'] or not ack.get('verified_local_archive'):
        return None
    mapped = ROOT / 'reports/optimization/complete_soc' / winner['variant'] / 'mapped_evaluation.json'
    if not mapped.exists() or not all(r['passed'] for r in json.loads(mapped.read_text())):
        return None
    old = json.loads((ROOT / 'build/optimization/ffn_transport/frozen_baseline/parent.json').read_text())
    if winner['variant'].startswith('ffn_tr_'):
        from ffn_transport import load as transport_load
        effective = transport_load(winner['variant'])['effective_changes']
    else:
        effective = old['effective_changes']
    parents = dict(W=snapshot(winner, BUILD / 'frozen/W', effective),
                   B=snapshot(old['state'], BUILD / 'frozen/B', old['effective_changes']))
    dump(BUILD / 'frozen/transport-selection.json', selection)
    dump(path, parents)
    return parents


def adopt(row):
    return snapshot(row, BUILD / 'accepted_parents' / row['variant'], load(row['variant'])['effective_changes'])


def create(label, parent, code=None, hardware=(), firmware_parent=None, purpose='experiment', firmware_changes=()):
    name = 'ffn_cg_' + label
    fw = firmware_parent or parent
    manifest = dict(variant=name, parent_variant=parent['variant'], parent=parent,
        firmware_parent=fw, compiler=code or fw.get('compiler', compiler()), hardware=sorted(hardware),
        firmware_changes=sorted(firmware_changes),
        features=parent['features'], effective_changes=dict(parent['effective_changes']),
        changes=dict(stream=True, small_input=True, row_group=1, double_buffer=True),
        purpose=purpose, numerical_package='models/kwt_unified_optimized_v1',
        objective=['mean_task_energy', 'throughput', 'budget_area'])
    path = MANIFESTS / (name + '.json')
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise RuntimeError('Frozen candidate differs: ' + name)
    if not path.exists():
        dump(path, manifest)
    return name
