"""Create twelve local RTL task fixtures, one true FFN input for each parameter set."""

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / 'data/numerical/fixed16_v1/ffn_vectors'
    source = sorted(directory.glob('*.npz'))[0]
    output = ROOT / 'data/numerical/fixed16_v1/ffn_tasks'
    output.mkdir(parents=True, exist_ok=True)
    manifest = {'purpose': 'local undergraduate RTL fixtures covering twelve parameter sets',
                'official_performance_tasks': False, 'source_sample_id': source.stem,
                'parameter_manifest_sha256': (ROOT / 'models/kwt1_fixed16_v1/manifest.sha256').read_text().strip(),
                'tasks': []}
    with np.load(source) as arrays:
        for layer in range(12):
            task = {'layer': layer, 'parameter_file': f'models/kwt1_fixed16_v1/layer_{layer:02d}.bin'}
            for kind in ['input', 'output']:
                values = arrays[f'layer_{layer:02d}_{kind}_codes'].astype('<i2')
                path = output / f'layer_{layer:02d}_{kind}.bin'
                path.write_bytes(values.tobytes(order='C'))
                path.with_suffix('.hex').write_text(''.join(f'{int(value):04x}\n' for value in values.view('<u2').flat), encoding='ascii')
                task[kind] = {'file': path.name, 'shape': list(values.shape),
                              'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            manifest['tasks'].append(task)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Exported 12 local FFN RTL fixtures; not official performance tasks.')


if __name__ == '__main__':
    main()
