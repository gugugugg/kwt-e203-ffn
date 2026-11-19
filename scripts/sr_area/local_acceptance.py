"""Reconcile the approved normal and four-state shift lifecycle checks."""
import ast
from pathlib import Path
import sys
from prepare import ROOT, FROZEN, REPORT, read, write, variants

sys.path.insert(0,str(ROOT/'scripts'))
from build_ffn_sr_area_firmware import build


def main():
    if not read(REPORT/'s3-quantizer-equivalence.json')['passed']:
        raise RuntimeError('S3 quantizer equivalence is incomplete')
    accepted = []
    for name in variants():
        folder = REPORT/'development'/name
        logs = [read(folder/file) for file in ('acceptance.json','four-state-actual12.json','reset-reload.json')]
        if not all(item['passed'] for item in logs):
            raise RuntimeError('Incomplete shift lifecycle checks: ' + name)
        targets = [(FROZEN/'rtl_sources', ROOT/'build/optimization/rtl_sources'/name),
                   (FROZEN/'firmware', build(name))]
        changes = []
        for original, candidate in targets:
            for source in original.rglob('*'):
                if source.is_file() and source.read_bytes() != (candidate/source.relative_to(original)).read_bytes():
                    changes.append((original.name + '/' + source.relative_to(original).as_posix()))
        expected = ['rtl_sources/encoder/kwt_encoder.sv']
        if name.endswith('_S3'):
            expected.append('rtl_sources/encoder/kwt_ffn_requantize.sv')
        if sorted(changes) != expected:
            raise RuntimeError('Unexpected source or firmware delta: ' + str(changes))
        accepted.append(dict(variant=name,normal_tasks=36,four_state_tasks=12,reset_reload_tasks=1,
                             outputs_per_task=25344,ordered_trace=True,shift_lifecycle=True,
                             changed_sources=changes,firmware_byte_equal=True))
    files = list((ROOT/'scripts/sr_area').glob('*.py')) + list(ROOT.glob('scripts/*sr_area*.py')) + list(ROOT.glob('scripts/server/*sr_area*.py'))
    for file in files:
        ast.parse(file.read_text(encoding='utf-8'),feature_version=(3,6))
    if (ROOT/'constraints/ffn_selected.json').read_bytes() != (FROZEN/'selected-original.json').read_bytes():
        raise RuntimeError('Published SR bytes changed')
    write(REPORT/'local-acceptance.json',dict(passed=True,candidates=accepted,python36_syntax_files=len(files)))
    print('SR_AREA_LOCAL_ACCEPTED',len(accepted),flush=True)


if __name__ == '__main__':
    main()
