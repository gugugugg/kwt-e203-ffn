"""Accepted B/X checkpoints and the authorized seventh-round matrix."""
import json
from ffn_adaptive import ROOT, copy_tree, dump, rank, features
from ffn_residual import prove_bias32, prove_zero_schedule

REPORT = ROOT / 'reports/optimization/ffn_joint_power'
BUILD = ROOT / 'build/optimization/ffn_joint_power'
MANIFESTS = ROOT / 'constraints/ffn_joint_power/candidates'
AREA_LIMIT = .225502163
POWER_LIMIT = .020750491542456676
THROUGHPUT_MIN = 1000


def load(name):
    return json.loads((MANIFESTS / (name + '.json')).read_text())


def candidates():
    return {p.stem: json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}


def freeze():
    path = BUILD / 'frozen/parent.json'
    if path.exists():
        return json.loads(path.read_text())
    previous = ROOT / 'reports/optimization/ffn_area_power'
    selection = json.loads((previous / 'final-selection.json').read_text())
    accepted = json.loads((previous / 'local-acceptance-check.json').read_text())
    if not accepted['passed'] or not accepted['native_ack_confirmed']:
        raise RuntimeError('Read completed sixth-round local/native acceptance')
    rows = {r['variant']: r for r in selection['ranking']}
    row = rows['ffn_ap_X']
    config = json.loads((ROOT / 'build/optimization/complete_soc/ffn_ap_X/configuration.json').read_text())
    manifest = json.loads((ROOT / 'constraints/ffn_area_power/candidates/ffn_ap_X.json').read_text())
    folder = BUILD / 'frozen/ffn_ap_X'
    for origin, leaf in [(config['source_snapshot'], 'rtl_sources'), (config['firmware'], 'firmware')]:
        copy_tree(ROOT / origin, folder / leaf)
    program = ROOT / config['firmware'] / 'input-files'
    if not program.exists():
        program = ROOT / manifest['parent']['program']
    copy_tree(program, folder / 'program')
    copy_tree(ROOT / config['linear_images'], BUILD / 'frozen/images')
    metadata = json.loads((folder / 'firmware/firmware.json').read_text())
    record = dict(variant=row['variant'], state=row, main_baseline=rows['ffn_tp_CROSS'],
                  configuration=config, features=features(row), effective_changes=manifest['effective_changes'],
                  profile=json.loads((ROOT / row['profile']).read_text()),
                  compiler=metadata.get('compiler', manifest['compiler']), pio_program=manifest['pio_program'],
                  firmware=(folder / 'firmware').relative_to(ROOT).as_posix(),
                  source_snapshot=(folder / 'rtl_sources').relative_to(ROOT).as_posix(),
                  program=(folder / 'program').relative_to(ROOT).as_posix(), layout=manifest['layout'],
                  dma=True, output_dma=True, flook=manifest.get('flook', False))
    dump(folder / 'parent.json', record)
    dump(BUILD / 'frozen/previous-selection.json', selection)
    dump(path, record)
    return record


def create(label, parent, hardware):
    name = 'ffn_jp_' + label
    pair = 'M2' in hardware
    effective = dict(parent['effective_changes'], joint_power_hardware=list(hardware), row_group=2 if pair else 1)
    row = dict(variant=name, parent_variant=parent['variant'], parent=parent, features=parent['features'],
               effective_changes=effective, changes=dict(stream=True, small_input=True, row_group=2 if pair else 1,
                                                        double_buffer=True),
               layout=parent['layout'], dma=True, output_dma=True, flook=parent['flook'], hardware=list(hardware),
               purpose='experiment', pio_program=parent['pio_program'], compiler=parent['compiler'],
               loader='required_data_v1', objective=['joint_feasible', 'mean_task_energy', 'throughput', 'budget_area'],
               numerical_package='models/kwt_unified_optimized_v1')
    path = MANIFESTS / (name + '.json')
    if path.exists() and json.loads(path.read_text()) != row:
        raise RuntimeError('Read the frozen seventh-round candidate: ' + name)
    if not path.exists():
        dump(path, row)
    return name


def joint_feasible(row):
    return (row.get('stage') == 'formal_passed' and row['throughput_per_second'] >= THROUGHPUT_MIN
            and row['mean_power_w'] < POWER_LIMIT
            and row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'] < AREA_LIMIT)


def same_rtl(name, manifest):
    from ffn_tile_pipeline import same_rtl as previous
    return previous(name, manifest)
