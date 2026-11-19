"""Freeze the accepted fourth-round winner and the finite fifth-round matrix."""
import json
from ffn_adaptive import ROOT, copy_tree, dump, rank, features
from ffn_residual import prove_bias32, prove_zero_schedule

REPORT = ROOT / 'reports/optimization/ffn_tile_pipeline'
BUILD = ROOT / 'build/optimization/ffn_tile_pipeline'
MANIFESTS = ROOT / 'constraints/ffn_tile_pipeline/candidates'


def load(name):
    return json.loads((MANIFESTS / (name + '.json')).read_text())


def candidates():
    return {p.stem: json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}


def snapshot(row, folder):
    path = folder / 'parent.json'
    if path.exists():
        return json.loads(path.read_text())
    if row['variant'].startswith('ffn_tp_'):
        manifest = load(row['variant'])
    else:
        from ffn_post_dma import load as previous
        manifest = previous(row['variant'])
    config = json.loads((ROOT / 'build/optimization/complete_soc' / row['variant'] / 'configuration.json').read_text())
    copy_tree(ROOT / config['source_snapshot'], folder / 'rtl_sources')
    copy_tree(ROOT / config['firmware'], folder / 'firmware')
    program = ROOT / config['firmware'] / 'input-files'
    if not program.exists():
        program = ROOT / manifest['parent']['program']
    copy_tree(program, folder / 'program')
    metadata = json.loads((folder / 'firmware/firmware.json').read_text())
    record = dict(variant=row['variant'], state=row, configuration=config, features=features(row),
                  effective_changes=manifest['effective_changes'], profile=json.loads((ROOT / row['profile']).read_text()),
                  compiler=metadata.get('compiler', manifest['compiler']), pio_program=manifest['pio_program'],
                  firmware=(folder / 'firmware').relative_to(ROOT).as_posix(),
                  source_snapshot=(folder / 'rtl_sources').relative_to(ROOT).as_posix(),
                  program=(folder / 'program').relative_to(ROOT).as_posix(), layout=manifest['layout'],
                  dma=manifest['dma'], output_dma=manifest['output_dma'], flook=manifest.get('flook', False))
    dump(path, record)
    return record


def freeze():
    path = BUILD / 'frozen/parent.json'
    if path.exists():
        return json.loads(path.read_text())
    prior = ROOT / 'reports/optimization/ffn_post_dma'
    status = json.loads((prior / 'delivery-status.json').read_text())
    selection = json.loads((prior / 'final-selection.json').read_text())
    ack = json.loads((prior / 'local-sync-confirmed.json').read_text())
    winner = dict(selection['winner'])
    if not status['complete'] or not selection['complete'] or not ack['verified_local_archive']:
        raise RuntimeError('Fourth-round complete local delivery is required')
    if status['winner'] != winner['variant'] or ack['winner'] != winner['variant']:
        raise RuntimeError('Fourth-round selection and local acknowledgement differ')
    if json.loads((ROOT / 'constraints/ffn_selected.json').read_text())['variant'] != winner['variant']:
        raise RuntimeError('Selected source must be the accepted fourth-round winner')
    mapped = ROOT / 'reports/optimization/complete_soc' / winner['variant'] / 'mapped_evaluation.json'
    if not all(r['passed'] for r in json.loads(mapped.read_text())) or not winner['assessment_clock_gating']['passed']:
        raise RuntimeError('Read the accepted mapped and official timing evidence')
    folder = ROOT / 'reports/optimization/complete_soc' / winner['variant']
    tasks = sorted([t for p in folder.glob('task_*.json') for t in json.loads(p.read_text())['tasks']], key=lambda t: t['case'])
    powers = {p['case']: p for p in winner['metrics']['power_reports']}
    energy = sum(powers[t['case']]['total_w'] * t['cycles'] / 150000000 for t in tasks)
    winner.update(mean_energy_j=energy / len(tasks), mean_power_w=energy / (sum(t['cycles'] for t in tasks) / 150000000))
    dump(BUILD / 'frozen/previous-selection.json', selection)
    parent = snapshot(winner, BUILD / 'frozen' / winner['variant'])
    dump(path, parent)
    return parent


def create(label, parent, hardware=(), purpose='experiment'):
    name = 'ffn_tp_' + label
    inherited = parent['effective_changes'].get('tile_pipeline_hardware', [])
    effective = dict(parent['effective_changes'], tile_pipeline_hardware=sorted(set(inherited) | set(hardware)))
    record = dict(variant=name, parent_variant=parent['variant'], parent=parent, features=parent['features'],
                  effective_changes=effective, changes=dict(stream=True, small_input=True, row_group=1, double_buffer=True),
                  layout=parent['layout'], dma=parent['dma'], output_dma=parent['output_dma'],
                  flook=parent.get('flook', False), hardware=list(hardware), purpose=purpose,
                  pio_program=parent['pio_program'], compiler=parent['compiler'], loader='required_data_v1',
                  objective=['mean_task_energy', 'throughput', 'budget_area'], numerical_package='models/kwt_unified_optimized_v1')
    path = MANIFESTS / (name + '.json')
    if path.exists() and json.loads(path.read_text()) != record:
        raise RuntimeError('Frozen fifth-round candidate differs: ' + name)
    if not path.exists():
        dump(path, record)
    return name


def adopt(row):
    return snapshot(row, BUILD / 'accepted_parents' / row['variant'])


def same_rtl(name, manifest):
    from ffn_post_dma import same_rtl as previous
    return previous(name, manifest)
