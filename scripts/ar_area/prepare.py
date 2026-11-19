"""Freeze the published AR inputs and derive two independent shift candidates."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'build/optimization/ffn_ar_area'
REPORT = ROOT / 'reports/optimization/ffn_ar_area'
FROZEN = BUILD / 'frozen'
sys.path.insert(0, str(ROOT / 'scripts'))
from c_final_energy.prepare import shared_shift


def variants():
    return ['ffn_ara_SS', 'ffn_ara_SR']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def freeze():
    selected = read(ROOT / 'constraints/ffn_selected.json')
    receipt = read(ROOT / 'reports/submission/car-AR-release-20261105/native-final-receipt.json')
    if selected['variant'] != 'ffn_car_AR' or not receipt['complete']:
        raise RuntimeError('Read the published and accepted AR release')
    if (FROZEN / 'parent.json').exists():
        return
    FROZEN.mkdir(parents=True, exist_ok=True)
    parent = read(ROOT / selected['adaptive_manifest'])
    parent.pop('parent', None)
    write(FROZEN / 'parent-manifest-original.json', parent)
    parent.update(state=selected['measured'], profile=selected['implementation'], configuration=selected,
                  firmware='build/optimization/ffn_ar_area/frozen/firmware',
                  source_snapshot='build/optimization/ffn_ar_area/frozen/rtl_sources',
                  program='build/optimization/ffn_ar_area/frozen/program')
    for source, target in [(selected['source_snapshot'], 'rtl_sources'), (selected['firmware'], 'firmware'),
                           (selected['linear_images'], 'images'), ('build/optimization/ffn_c_area/frozen/program', 'program')]:
        shutil.copytree(str(ROOT/source), str(FROZEN/target))
    for source, target in [('constraints/ffn_selected.json','selected-original.json'),
                           ('constraints/ffn_next_objective.json','previous-objective.json'),
                           ('constraints/ffn_submission_priority.json','previous-priority.json')]:
        shutil.copyfile(str(ROOT/source), str(FROZEN/target))
    write(FROZEN/'parent.json', parent)
    write(REPORT/'objective.json', dict(baseline='ffn_car_AR', area_strictly_below_mm2=0.251108309,
          preferred_energy_at_most_j=1.800626077963921e-05, throughput_at_least=1000,
          candidates=variants(), energy_increase_hard_failure=False, publication_changed=False))


def shift_no_reset(text):
    old = """        always @(posedge shift_register_clk or negedge rst_n)begin
            if(!rst_n)shifts[jp_lane]<=0;
            else if(seed_update)shifts[jp_lane]<=$signed(jp_shift_return[(jp_column%2)*8+:8]);
        end
"""
    new = """        always @(posedge shift_register_clk)begin
            if(seed_update)shifts[jp_lane]<=$signed(jp_shift_return[(jp_column%2)*8+:8]);
        end
"""
    if text.count(old) != 1:
        raise RuntimeError('Read the frozen AR shift block')
    return text.replace(old, new, 1)


def prepare(name):
    if name not in variants():
        raise ValueError(name)
    kind = name.rsplit('_', 1)[1]
    parent = read(FROZEN/'parent.json')
    source = FROZEN/'rtl_sources'
    target = ROOT/'build/optimization/rtl_sources'/name
    changed = []
    for path in source.rglob('*'):
        if not path.is_file():
            continue
        value = path.read_bytes()
        rel = path.relative_to(source)
        if rel.as_posix() == 'encoder/kwt_encoder.sv':
            text = value.decode('utf-8').replace('\r\n', '\n')
            updated = (shared_shift if kind == 'SS' else shift_no_reset)(text)
            if updated == text:
                raise RuntimeError('Shift transformation did not apply')
            value = updated.encode('utf-8')
            changed.append(rel.as_posix())
        dest = target/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_bytes() != value:
            dest.write_bytes(value)
    if changed != ['encoder/kwt_encoder.sv']:
        raise RuntimeError('Expected only the shift RTL change')
    manifest = {key:value for key,value in parent.items()
                if key not in ('state','profile','firmware','source_snapshot','configuration','program')}
    manifest.update(variant=name, parent_variant='ffn_car_AR', parent=parent,
                    hardware=list(parent['hardware'])+[kind], ar_area_hardware=[kind],
                    effective_changes=dict(parent['effective_changes'], ar_area_hardware=[kind]),
                    purpose='experiment', objective=['area_below_AR','throughput_at_least_1000','prefer_energy_not_increased'],
                    automatic_release_switch=False)
    write(ROOT/'constraints/ffn_ar_area/candidates'/(name+'.json'), manifest)
    write(REPORT/(name+'-source-changes.json'), dict(parent='ffn_car_AR', candidate=name,
          changed_sources=changed, unaffected_files_byte_equal=True))
    return manifest, target


if __name__ == '__main__':
    freeze()
    for variant in variants():
        prepare(variant)
