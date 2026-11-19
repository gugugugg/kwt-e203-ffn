"""Frozen fifth-round parent and approved sixth-round configurations."""
import json
from ffn_adaptive import ROOT, copy_tree, dump, rank, features
from ffn_residual import prove_bias32, prove_zero_schedule

REPORT = ROOT / 'reports/optimization/ffn_area_power'
BUILD = ROOT / 'build/optimization/ffn_area_power'
MANIFESTS = ROOT / 'constraints/ffn_area_power/candidates'
AREA_LIMIT = 0.225502163
POWER_LIMIT = 0.020750491542456676
THROUGHPUT_MIN = 1000


def load(name):
    return json.loads((MANIFESTS / (name + '.json')).read_text())


def candidates():
    return {p.stem: json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}


def freeze():
    path = BUILD / 'frozen/parent.json'
    if path.exists():
        return json.loads(path.read_text())
    prior = ROOT / 'reports/optimization/ffn_tile_pipeline'
    status = json.loads((prior / 'delivery-status.json').read_text())
    selection = json.loads((prior / 'final-selection.json').read_text())
    ack = json.loads((prior / 'local-sync-confirmed.json').read_text())
    row = selection['winner']
    if not status['complete'] or not selection['complete'] or not ack['verified_local_archive']:
        raise RuntimeError('Fifth-round acceptance and complete local delivery are required')
    if not all(v == 'ffn_tp_CROSS' for v in [row['variant'], status['winner'], ack['winner'],
            json.loads((ROOT / 'constraints/ffn_selected.json').read_text())['variant']]):
        raise RuntimeError('Read the accepted fifth-round selection and acknowledgement')
    mapped = ROOT / 'reports/optimization/complete_soc' / row['variant'] / 'mapped_evaluation.json'
    if not all(r['passed'] for r in json.loads(mapped.read_text())) or not row['assessment_clock_gating']['passed']:
        raise RuntimeError('Fifth-round mapped and official timing evidence is incomplete')
    from ffn_tile_pipeline import load as previous
    manifest = previous(row['variant'])
    config = json.loads((ROOT / 'build/optimization/complete_soc' / row['variant'] / 'configuration.json').read_text())
    folder = BUILD / 'frozen' / row['variant']
    copy_tree(ROOT / config['source_snapshot'], folder / 'rtl_sources')
    copy_tree(ROOT / config['firmware'], folder / 'firmware')
    program = ROOT / config['firmware'] / 'input-files'
    if not program.exists():
        program = ROOT / manifest['parent']['program']
    copy_tree(program, folder / 'program')
    copy_tree(ROOT / config['linear_images'], BUILD / 'frozen/images')
    metadata = json.loads((folder / 'firmware/firmware.json').read_text())
    record = dict(variant=row['variant'], state=row, configuration=config, features=features(row),
                  effective_changes=manifest['effective_changes'], profile=json.loads((ROOT / row['profile']).read_text()),
                  compiler=metadata.get('compiler', manifest['compiler']), pio_program=manifest['pio_program'],
                  firmware=(folder / 'firmware').relative_to(ROOT).as_posix(),
                  source_snapshot=(folder / 'rtl_sources').relative_to(ROOT).as_posix(),
                  program=(folder / 'program').relative_to(ROOT).as_posix(), layout=manifest['layout'],
                  dma=manifest['dma'], output_dma=manifest['output_dma'], flook=manifest.get('flook', False))
    dump(folder / 'parent.json', record)
    dump(BUILD / 'frozen/previous-selection.json', selection)
    dump(path, record)
    return record


def create(label, parent, hardware=()):
    name = 'ffn_ap_' + label
    record = dict(variant=name, parent_variant=parent['variant'], parent=parent, features=parent['features'],
                  effective_changes=dict(parent['effective_changes'], area_power_hardware=list(hardware)),
                  changes=dict(stream=True, small_input=True, row_group=1, double_buffer=True),
                  layout=parent['layout'], dma=parent['dma'], output_dma=parent['output_dma'],
                  flook=parent.get('flook', False), hardware=list(hardware), purpose='experiment',
                  pio_program=parent['pio_program'], compiler=parent['compiler'], loader='required_data_v1',
                  objective=['joint_feasible', 'mean_task_energy', 'throughput', 'budget_area'],
                  numerical_package='models/kwt_unified_optimized_v1')
    path = MANIFESTS / (name + '.json')
    if path.exists() and json.loads(path.read_text()) != record:
        raise RuntimeError('Frozen sixth-round candidate differs: ' + name)
    if not path.exists():
        dump(path, record)
    return name


def joint_feasible(row):
    return (row.get('stage') == 'formal_passed' and row['throughput_per_second'] >= THROUGHPUT_MIN
            and row['mean_power_w'] < POWER_LIMIT
            and row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'] < AREA_LIMIT)


def same_rtl(name, manifest):
    from ffn_tile_pipeline import same_rtl as previous
    return previous(name, manifest)
