"""Freeze published SR and derive independent shift compression candidates."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'build/optimization/ffn_sr_area'
REPORT = ROOT / 'reports/optimization/ffn_sr_area'
FROZEN = BUILD / 'frozen'
sys.path.insert(0, str(ROOT / 'scripts'))
from ar_area.prepare import shift_no_reset
from c_final_energy.prepare import shared_shift


def variants():
    return ['ffn_sra_S3', 'ffn_sra_SS']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def freeze():
    selected = read(ROOT / 'constraints/ffn_selected.json')
    receipt = read(ROOT / 'reports/submission/ara-SR-release-20261105/native-final-receipt.json')
    if selected['variant'] != 'ffn_ara_SR' or not receipt['complete'] or receipt['variant'] != selected['variant']:
        raise RuntimeError('Read the published and accepted SR release')
    if (FROZEN / 'parent.json').exists():
        return
    FROZEN.mkdir(parents=True, exist_ok=True)
    parent = read(ROOT / selected['adaptive_manifest'])
    parent.pop('parent', None)
    write(FROZEN / 'parent-manifest-original.json', parent)
    parent.update(state=selected['measured'], profile=selected['implementation'], configuration=selected,
                  firmware='build/optimization/ffn_sr_area/frozen/firmware',
                  source_snapshot='build/optimization/ffn_sr_area/frozen/rtl_sources',
                  program='build/optimization/ffn_sr_area/frozen/program')
    for source, target in [(selected['source_snapshot'], 'rtl_sources'), (selected['firmware'], 'firmware'),
                           (selected['linear_images'], 'images'), ('build/optimization/ffn_ar_area/frozen/program', 'program')]:
        shutil.copytree(str(ROOT/source), str(FROZEN/target))
    for source, target in [('constraints/ffn_selected.json','selected-original.json'),
                           ('constraints/ffn_next_objective.json','previous-objective.json'),
                           ('constraints/ffn_submission_priority.json','previous-priority.json'),
                           ('reports/submission/ara-SR-release-20261105/native-final-receipt.json','sr-release-receipt.json')]:
        shutil.copyfile(str(ROOT/source), str(FROZEN/target))
    write(FROZEN/'references/SS.json', read(ROOT/'reports/optimization/ffn_ar_area/ffn_ara_SS.json'))
    write(FROZEN/'parent.json', parent)
    write(REPORT/'objective.json', dict(baseline='ffn_ara_SR', area_strictly_below_mm2=0.250707394,
          preferred_energy_at_most_j=1.7990618656009402e-05, throughput_at_least=1000,
          candidates=variants(), energy_increase_hard_failure=False, publication_changed=False))


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Unexpected frozen SR source: ' + old.splitlines()[0])
    return text.replace(old, new, 1)


def share_without_reset(text):
    original = """        always @(posedge shift_register_clk or negedge rst_n)begin
            if(!rst_n)shifts[jp_lane]<=0;
            else if(seed_update)shifts[jp_lane]<=$signed(jp_shift_return[(jp_column%2)*8+:8]);
        end
"""
    # Adapt the historical sharing transform to its original input shape.
    shared = shared_shift(replace_once(text, shift_no_reset(original), original))
    return replace_once(shared, """        always @(posedge shift_register_clk or negedge rst_n)begin
            if(!rst_n)shifts[ss_column]<=0;
            else if(shift_update)shifts[ss_column]<=$signed(jp_shift_return[(ss_column%2)*8+:8]);
        end
""", """        always @(posedge shift_register_clk)begin
            if(shift_update)shifts[ss_column]<=$signed(jp_shift_return[(ss_column%2)*8+:8]);
        end
""")


def encode_shift_state(text):
    text = replace_once(text, 'reg signed [7:0] shifts[0:MAC_LANES-1];',
                        'reg [2:0] shifts[0:MAC_LANES-1];')
    latch = '    always_latch if(!clk)jp_shift_return=shift_rdata;'
    text = replace_once(text, latch, latch + """
    function automatic [2:0] shift_code(input [7:0] raw_shift);
        case(raw_shift)
            8'd13:shift_code=3'd1;
            8'd14:shift_code=3'd2;
            8'd15:shift_code=3'd3;
            8'd16:shift_code=3'd4;
            8'd17:shift_code=3'd5;
            8'd18:shift_code=3'd6;
            default:shift_code=3'd0;
        endcase
    endfunction
    wire [2:0] shift_code_low=shift_code(jp_shift_return[7:0]);
    wire [2:0] shift_code_high=shift_code(jp_shift_return[15:8]);""")
    return replace_once(text, 'if(seed_update)shifts[jp_lane]<=$signed(jp_shift_return[(jp_column%2)*8+:8]);',
                        'if(seed_update)shifts[jp_lane]<=jp_column%2==0?shift_code_low:shift_code_high;')


def coded_quantizer(text):
    text = replace_once(text, 'input wire signed [7:0] shift,', 'input wire [2:0] shift,')
    for raw in range(13, 19):
        text = replace_once(text, '            %d:begin' % raw, "            3'd%d:begin" % (raw-12))
    return text


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
            updated = (share_without_reset if kind == 'SS' else encode_shift_state)(text)
            if updated == text:
                raise RuntimeError('Shift transformation did not apply')
            value = updated.encode('utf-8')
            changed.append(rel.as_posix())
        elif kind == 'S3' and rel.as_posix() == 'encoder/kwt_ffn_requantize.sv':
            value = coded_quantizer(value.decode('utf-8')).encode('utf-8')
            changed.append(rel.as_posix())
        dest = target/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_bytes() != value:
            dest.write_bytes(value)
    expected = ['encoder/kwt_encoder.sv']
    if kind == 'S3':
        expected.append('encoder/kwt_ffn_requantize.sv')
    if sorted(changed) != expected:
        raise RuntimeError('Expected only the shift RTL change')
    manifest = {key:value for key,value in parent.items()
                if key not in ('state','profile','firmware','source_snapshot','configuration','program')}
    manifest.update(variant=name, parent_variant='ffn_ara_SR', parent=parent,
                    hardware=list(parent['hardware'])+[kind], sr_area_hardware=[kind],
                    effective_changes=dict(parent['effective_changes'], sr_area_hardware=[kind]),
                    purpose='experiment', objective=['area_below_SR','throughput_at_least_1000','prefer_energy_not_increased'],
                    automatic_release_switch=False)
    write(ROOT/'constraints/ffn_sr_area/candidates'/(name+'.json'), manifest)
    write(REPORT/(name+'-source-changes.json'), dict(parent='ffn_ara_SR', candidate=name,
          changed_sources=changed, unaffected_files_byte_equal=True))
    return manifest, target


if __name__ == '__main__':
    freeze()
    for variant in variants():
        prepare(variant)
