"""Derive the sole AH implementation from the accepted SR snapshot."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VARIANT = 'ffn_sr_ah'
REPORT = ROOT/'reports/optimization'/VARIANT
BUILD = ROOT/'build/optimization'/VARIANT
CORE = Path('encoder/kwt_encoder.sv')
WRAPPER = Path('encoder_bus/kwt_icb_encoder.sv')


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')


def edit(data, old, new):
    if data.count(old) != 1:
        raise ValueError('Frozen SR source does not have exactly one match: '+old)
    return data.replace(old, new, 1)


def prepare():
    selected = ROOT/'constraints/ffn_selected.json'
    baseline = json.loads(selected.read_text())
    receipt = ROOT/'reports/submission/ara-SR-release-20261105/completion.json'
    if baseline['variant'] != 'ffn_ara_SR' or not json.loads(receipt.read_text())['complete']:
        raise RuntimeError('Expected the accepted SR release')
    source = ROOT/baseline['source_snapshot']
    candidate = ROOT/'build/optimization/rtl_sources'/VARIANT
    shutil.copytree(str(source), str(candidate), dirs_exist_ok=True)
    text = edit((source/CORE).read_text(), 'CLOCK_GATING=1\n',
                'CLOCK_GATING=1, ACC_ICG_UPDATE=0\n')
    text = edit(text, 'else if(mac_update)accumulator[jp_lane]<=',
                'else if((ACC_ICG_UPDATE && CLOCK_GATING) || mac_update)accumulator[jp_lane]<=')
    (candidate/CORE).write_bytes(text.encode('utf-8'))
    wrapper = edit((source/WRAPPER).read_text(),
        "kwt_encoder core(.clk(clk),.rst_n(rst_n&&!soft_reset),.linear_mode(linear_mode),.clock_test_enable(1'b0),",
        "kwt_encoder #(.ACC_ICG_UPDATE(1)) core(.clk(clk),.rst_n(rst_n&&!soft_reset),.linear_mode(linear_mode),.clock_test_enable(1'b0),")
    (candidate/WRAPPER).write_bytes(wrapper.encode('utf-8'))
    changed = sorted(p.relative_to(source).as_posix() for p in source.rglob('*')
                     if p.is_file() and p.read_bytes() != (candidate/p.relative_to(source)).read_bytes())
    if changed != sorted([CORE.as_posix(), WRAPPER.as_posix()]):
        raise RuntimeError('Unexpected changes to the SR source')
    REPORT.mkdir(parents=True, exist_ok=True)
    for relative in (CORE, WRAPPER):
        path = REPORT/'candidate-rtl'/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate/relative,path)
    shutil.copyfile(selected,REPORT/'baseline-selected.json')
    shutil.copyfile(receipt,REPORT/'baseline-release.json')
    dump(REPORT/'objective.json',dict(variant=VARIANT, baseline='ffn_ara_SR',
        maximum_total_cycles=1200000, maximum_area_exclusive_mm2=0.250707394,
        maximum_power_exclusive_w=0.027318392824690587,
        maximum_mean_energy_j=1.7990618656009402e-05, changed=changed, publication_changed=False))
    return json.loads((ROOT/baseline['adaptive_manifest']).read_text()), source, candidate


if __name__ == '__main__':
    prepare()

