"""Check saved artifacts, partition provenance and an independent NumPy encoder."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.kwt_numpy import encoder  # noqa: E402


def main():
    summary = json.loads((ROOT / 'reports/data/floating-reference-summary.json').read_text())
    if summary['status'] != 'passed':
        raise ValueError('Reference export is incomplete.')
    for name, expected in summary['manifest_sha256'].items():
        actual = hashlib.sha256((ROOT / 'data/manifests' / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('Changed manifest: ' + name)
    weights_file = ROOT / 'models/kwt1_float32/parameters_float32.npz'
    with np.load(weights_file) as archive:
        parameters = {key: archive[key] for key in archive.files}
    if len(parameters) != 162 or sum(value.size for value in parameters.values()) != 607308:
        raise ValueError('Incomplete parameter export.')
    golden_dir = ROOT / 'data/reference/golden_validation24'
    errors = []
    for path in sorted(golden_dir.glob('*.npz')):
        with np.load(path) as stored:
            layers, logits = encoder(stored['encoder_input'], parameters)
            expected = np.stack([stored[f'layer_{i:02d}_output'] for i in range(12)])
            np.testing.assert_allclose(layers, expected, atol=5e-4, rtol=5e-4)
            np.testing.assert_allclose(logits, stored['logits'], atol=5e-4, rtol=5e-4)
            if np.argmax(logits) != np.argmax(stored['logits']):
                raise ValueError('Independent encoder prediction mismatch: ' + path.name)
            errors.append({'sample_id': path.stem, 'layers_max_abs': float(np.abs(layers - expected).max()),
                           'logits_max_abs': float(np.abs(logits - stored['logits']).max())})
    inventory = {}
    for name, count, split in [('calibration_train240', 240, 'training'),
                               ('validation_full', summary['validation_full']['count'], 'validation'),
                               ('validation_dev600', 600, 'validation')]:
        directory = ROOT / 'data/reference' / name
        records = [json.loads(line) for line in (directory / 'samples.jsonl').read_text().splitlines()]
        assert len(records) == count and all(row['split'] == split for row in records)
        labels = np.load(directory / 'labels.npy', mmap_mode='r')
        arrays = {}
        for key, shape in [('mfcc', (98, 40)), ('encoder_input', (99, 64)),
                           ('encoder_output', (99, 64)), ('encoder_layers', (12, 99, 64)), ('logits', (12,))]:
            value = np.load(directory / (key + '.npy'), mmap_mode='r')
            assert value.shape == (count,) + shape and value.dtype == np.dtype('<f4')
            for i in range(0, count, 100):
                assert np.isfinite(value[i:i + 100]).all()
            arrays[key] = value
        assert np.array_equal(labels, np.array([row['label_index'] for row in records]))
        assert np.array_equal(arrays['encoder_output'], arrays['encoder_layers'][:, -1])
        metrics = json.loads((directory / 'summary.json').read_text())
        assert int(np.sum(labels == arrays['logits'].argmax(axis=1))) == metrics['correct']
        inventory[name] = {'count': count, 'split': split, 'all_tensors_finite': True,
                           'last_layer_equals_encoder_output': True}
    validation_dir = ROOT / 'data/reference/validation_full'
    validation_rows = [json.loads(line) for line in (validation_dir / 'samples.jsonl').read_text().splitlines()]
    lookup = {row['sample_id']: i for i, row in enumerate(validation_rows)}
    for key in ['mfcc', 'encoder_input', 'encoder_output', 'logits']:
        full = np.load(validation_dir / (key + '.npy'), mmap_mode='r')
        for path in sorted(golden_dir.glob('*.npz')):
            with np.load(path) as stored:
                assert np.array_equal(full[lookup[path.stem]], stored[key])
    artifacts = {}
    paths = sorted((ROOT / 'data/reference').rglob('*.npy'))
    paths += sorted(golden_dir.glob('*.npz'))
    paths += sorted((ROOT / 'models/kwt1_float32').glob('*'))
    for path in paths:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                digest.update(chunk)
        artifacts[path.relative_to(ROOT).as_posix()] = {
            'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}
    (ROOT / 'reports/data/artifact-sha256.json').write_text(json.dumps(artifacts, indent=2), encoding='utf-8')
    result = {'status': 'passed', 'independent_numpy_encoder_samples': len(errors),
              'tolerances': {'atol': 5e-4, 'rtol': 5e-4}, 'numpy_errors': errors,
              'numpy_prediction_matches': len(errors), 'artifact_checks': inventory,
              'golden_vs_full_validation_bit_exact': True, 'artifacts_hashed': len(artifacts),
              'test_inference_performed': False}
    (ROOT / 'reports/data/reference-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
