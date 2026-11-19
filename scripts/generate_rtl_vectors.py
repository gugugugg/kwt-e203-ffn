"""Generate independent component cases and arbitrary full FFN tasks from frozen model."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.fixed_ops import dense, round_shift, saturate16  # noqa: E402
from sim.kwt_fixed import FixedKWT  # noqa: E402


def write_hex(path, values, bits):
    mask = (1 << bits) - 1
    with path.open('w', encoding='ascii', newline='\n') as stream:
        stream.writelines(f'{int(value) & mask:0{bits // 4}x}\n' for value in np.asarray(values).flat)


def main():
    out = ROOT / 'build/rtl/vectors'
    out.mkdir(parents=True, exist_ok=True)
    model = FixedKWT(ROOT / 'models/kwt1_fixed16_v1', backend='int64')
    rng = np.random.default_rng(20261021)
    cases = []
    for shift in [-30, -1, 0, 1, 2, 16, 31, 62]:
        for bias in [-65537, -65535, -5, -3, -1, 0, 1, 3, 5, 65535, 65537]:
            cases.append((np.zeros(64, np.int16), np.zeros(64, np.int16), bias, shift))
    for a, b in [(-32768, -32768), (-32768, 32767), (32767, 32767)]:
        for shift in [0, 16, 30, 40]:
            cases.append((np.full(64, a, np.int16), np.full(64, b, np.int16), -1234567, shift))
    for _ in range(128):
        a = rng.integers(-32768, 32768, 64, dtype=np.int16)
        b = rng.integers(-32768, 32768, 64, dtype=np.int16)
        cases.append((a, b, int(rng.integers(-(1 << 29), 1 << 29)), int(rng.integers(0, 45))))
    expected = [int(dense(a.reshape(1,64), b.reshape(64,1), [bias], shift, 0, 0,
                          'int64')[0,0]) for a,b,bias,shift in cases]
    write_hex(out / 'dot_a.hex', np.stack([row[0] for row in cases]), 16)
    write_hex(out / 'dot_b.hex', np.stack([row[1] for row in cases]), 16)
    write_hex(out / 'dot_bias.hex', [row[2] for row in cases], 64)
    write_hex(out / 'dot_shift.hex', [row[3] for row in cases], 8)
    write_hex(out / 'dot_expected.hex', expected, 16)
    requant = []
    for shift in [-30, -1, 0, 1, 2, 16, 31, 62]:
        values = [-32769, -32768, -32767, -65537, -65535, -5, -3, -1, 0, 1, 3, 5,
                  32767, 32768, 32769, 65535, 65537]
        if shift >= 0:
            values += [-(1 << 62)+1, -(1 << 61), (1 << 61), (1 << 62)-1]
        for value in values:
            result = int(saturate16(round_shift(np.array([value], np.int64), shift))[0])
            requant.append((value, shift, result))
    write_hex(out / 'requant_value.hex', [row[0] for row in requant], 64)
    write_hex(out / 'requant_shift.hex', [row[1] for row in requant], 8)
    write_hex(out / 'requant_expected.hex', [row[2] for row in requant], 16)
    fixtures = sorted((ROOT / 'data/numerical/fixed16_v1/ffn_vectors').glob('*.npz'))
    real = np.load(fixtures[0])
    tasks = []
    # Actual true per-layer norm1 inputs, one task for each of the 12 weight sets.
    for layer in range(12):
        x = real[f'layer_{layer:02d}_input_codes']
        y = model.ffn(x, layer, encoded=True)
        tasks.append((layer, x, y, 'real_validation_norm1'))
    # New inputs are calculated here, not copied from any saved answer file.
    for name, layer, x in [
        ('zeros', 0, np.zeros((99,64), np.int16)),
        ('full_range_random', 11, rng.integers(-32768,32768,(99,64),dtype=np.int16)),
    ]:
        tasks.append((layer, x, model.ffn(x, layer, encoded=True), name))
    for index, (layer, x, y, source) in enumerate(tasks):
        op = model.config['layers'][layer]['dense']['ffn.fc1']
        prefix = out / f'task_{index:02d}'
        write_hex(prefix.with_name(prefix.name + '_input.hex'), x, 16)
        write_hex(prefix.with_name(prefix.name + '_kernel.hex'), model.parameters[op['kernel']], 16)
        bias = model.parameters[op['bias']].astype('<i8').view('<u2')
        write_hex(prefix.with_name(prefix.name + '_bias.hex'), bias, 16)
        write_hex(prefix.with_name(prefix.name + '_expected.hex'), y, 16)
    (out / 'counts.svh').write_text(f'`define DOT_CASES {len(cases)}\n`define REQUANT_CASES {len(requant)}\n`define FFN_CASES {len(tasks)}\n', encoding='ascii')
    manifest = {'component_seed': 20261021, 'dot_cases': len(cases), 'requant_cases': len(requant),
                'ffn_tasks': [{'index': i, 'layer': layer, 'source': source,
                               'shift': model.config['layers'][layer]['dense']['ffn.fc1']['input_f'] +
                                        model.config['layers'][layer]['dense']['ffn.fc1']['weight_f'] -
                                        model.config['layers'][layer]['dense']['ffn.fc1']['output_f']}
                              for i,(layer,x,y,source) in enumerate(tasks)],
                'not_official_performance_tasks': True,
                'parameter_manifest_sha256': (model.directory / 'manifest.sha256').read_text().strip(),
                'files': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(out.glob('*.hex'))}}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Generated {len(cases)} dot, {len(requant)} requant, {len(tasks)} full FFN cases.')


if __name__ == '__main__':
    main()
