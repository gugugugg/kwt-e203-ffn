"""Derive the single RD source snapshot from the accepted SR release."""
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VARIANT = 'ffn_sr_rd'
REPORT = ROOT / 'reports/optimization' / VARIANT
BUILD = ROOT / 'build/optimization' / VARIANT
QUEUE = Path('encoder/kwt_joint_output_queue.sv')


def change(text):
    pairs = [
        ('row0_write,row0_read;', 'row0_write;'),
        ('row1_write,row1_read;', 'row1_write;'),
        ("read1_address=row1_read+8'(capture1);", 'read1_address=next_item[7:0];'),
        ("(row0_read+7'(capture0))", 'next_item[6:0]'),
        ('row0_write<=0;row0_read<=0;row0_count<=0;', 'row0_write<=0;row0_count<=0;'),
        ('row1_write<=0;row1_read<=0;row1_count<=0;', 'row1_write<=0;row1_count<=0;'),
        ("        row0_read<=row0_read+7'(capture0);\n", ''),
        ("        row1_read<=row1_read+8'(capture1);\n", ''),
    ]
    for old, new in pairs:
        expected = 2 if '<=0;' in old else 1
        if text.count(old) != expected:
            raise ValueError('Unexpected SR queue text for ' + old)
        text = text.replace(old, new)
    if re.search(r'\brow[01]_read\b', text):
        raise ValueError('SR pointer remains')
    return text


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def prepare():
    release_path = ROOT / 'constraints/ffn_selected.json'
    release = json.loads(release_path.read_text(encoding='utf-8'))
    receipt = ROOT / 'reports/submission/ara-SR-release-20261105/completion.json'
    if release['variant'] != 'ffn_ara_SR' or not json.loads(receipt.read_text())['complete']:
        raise RuntimeError('Expected accepted SR baseline')
    source = ROOT / release['source_snapshot']
    target = ROOT / 'build/optimization/rtl_sources' / VARIANT
    shutil.copytree(str(source), str(target), dirs_exist_ok=True)
    candidate = target / QUEUE
    candidate.write_text(change((source / QUEUE).read_text()), encoding='utf-8', newline='\n')
    assert sorted(str(p.relative_to(source).as_posix()) for p in source.rglob('*')
                  if p.is_file() and p.read_bytes() != (target / p.relative_to(source)).read_bytes()) == [QUEUE.as_posix()]
    REPORT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(candidate), str(REPORT / QUEUE.name))
    shutil.copyfile(str(release_path), str(REPORT / 'baseline-selected.json'))
    shutil.copyfile(str(receipt), str(REPORT / 'baseline-release.json'))
    dump(REPORT / 'objective.json', dict(variant=VARIANT, baseline=release['variant'],
         area_strictly_below_mm2=0.250707394, maximum_total_cycles=1185396,
         preferred_maximum_mean_energy_j=1.7990618656009402e-05, publication_changed=False))
    manifest = json.loads((ROOT / release['adaptive_manifest']).read_text())
    return manifest, source, target


if __name__ == '__main__':
    prepare()

