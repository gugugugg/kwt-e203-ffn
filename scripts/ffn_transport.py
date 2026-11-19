"""Frozen transport baseline and explicitly configured independent candidates."""
from pathlib import Path
import json
from ffn_adaptive import ROOT, copy_tree, dump, rank, features
from ffn_residual import prove_bias32, prove_zero_schedule

REPORT = ROOT / 'reports/optimization/ffn_transport'
BUILD = ROOT / 'build/optimization/ffn_transport'
MANIFESTS = ROOT / 'constraints/ffn_transport/candidates'


def candidates():
    return {p.stem: json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}


def load(name):
    return json.loads((MANIFESTS / (name + '.json')).read_text())


def freeze():
    path = BUILD / 'frozen_baseline/parent.json'
    if path.exists():
        return json.loads(path.read_text())
    config = json.loads((ROOT / 'constraints/ffn_selected.json').read_text())
    if config['variant'] != 'ffn_res_sixteen_O':
        raise RuntimeError('Inspect the selected version before freezing transport B')
    selection = json.loads((ROOT / 'reports/optimization/ffn_residual/final-selection.json').read_text())
    folder = path.parent
    source = ROOT / config['source_snapshot']
    text = (source / 'encoder/kwt_encoder.sv').read_text()
    if 'CLEAR:if(ZERO_CLEAR||clear_index==0)' not in text:
        raise RuntimeError('The accepted baseline clear policy differs from the reviewed snapshot')
    copy_tree(source, folder / 'rtl_sources')
    copy_tree(ROOT / config['firmware'], folder / 'firmware')
    previous = json.loads((ROOT / 'constraints/ffn_residual/candidates/ffn_res_sixteen_O.json').read_text())
    effective = dict(previous['effective_changes'], clear_last=0, zero_clear=False)
    record = dict(variant=config['variant'], state=config['measured'], features=features(config['measured']),
                  effective_changes=effective, configuration=config, profile=config['implementation'],
                  source_snapshot=(folder / 'rtl_sources').relative_to(ROOT).as_posix(),
                  firmware=(folder / 'firmware').relative_to(ROOT).as_posix())
    dump(folder / 'previous-selection.json', selection)
    dump(folder / 'selected.json', config)
    dump(path, record)
    return record


def software(base_cached=True, load_kernel='c4', output_kernel='c4'):
    return dict(base_cached=base_cached, load_kernel=load_kernel, output_kernel=output_kernel,
                load_group_words=4 if load_kernel == 'asm4' else int(load_kernel[1:]),
                output_group_words=4 if output_kernel == 'asm4' else int(output_kernel[1:]),
                row_group=1, double_buffer=True)


def create(label, firmware=None, hardware=(), parent=None, purpose='experiment'):
    parent = parent or freeze()
    name = 'ffn_tr_' + label
    hardware = sorted(hardware)
    effective = dict(parent['effective_changes'], clear_last=0, zero_clear=False)
    if 'V0' in hardware:
        effective['double_buffer'] = False
    effective['transport_hardware'] = sorted(set(parent['effective_changes'].get('transport_hardware', [])) | set(hardware))
    changes = dict(stream=True, small_input=True, row_group=1,
                   double_buffer=effective.get('double_buffer', True))
    manifest = dict(variant=name, parent_variant=parent['variant'], parent=parent,
                    features=parent['features'], changes=changes, effective_changes=effective,
                    hardware=hardware, software=firmware or software(), purpose=purpose,
                    numerical_package='models/kwt_unified_optimized_v1',
                    objective=['mean_task_energy', 'throughput', 'budget_area'])
    path = MANIFESTS / (name + '.json')
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise RuntimeError('A frozen transport experiment has a different configuration: ' + name)
    if not path.exists():
        dump(path, manifest)
    return name


def adopt(row):
    folder = BUILD / 'accepted_parents' / row['variant']
    path = folder / 'parent.json'
    if path.exists():
        return json.loads(path.read_text())
    manifest = load(row['variant'])
    config = json.loads((ROOT / 'build/optimization/complete_soc' / row['variant'] / 'configuration.json').read_text())
    copy_tree(ROOT / config['source_snapshot'], folder / 'rtl_sources')
    copy_tree(ROOT / config['firmware'], folder / 'firmware')
    result = dict(variant=row['variant'], state=row, features=row['features'],
                  effective_changes=manifest['effective_changes'], configuration=config,
                  profile=json.loads((ROOT / row['profile']).read_text()),
                  source_snapshot=(folder / 'rtl_sources').relative_to(ROOT).as_posix(),
                  firmware=(folder / 'firmware').relative_to(ROOT).as_posix())
    dump(path, result)
    return result
