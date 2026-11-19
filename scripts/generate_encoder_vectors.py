"""Fresh full-encoder traces; expected data is host-only, never loaded into RTL."""
import hashlib
import json
from math import isqrt
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.kwt_fixed import FixedKWT  # noqa: E402
from sim.fixed_ops import encode, round_divide  # noqa: E402

STAGES = ['q', 'k', 'v', 'qk_accumulator', 'attention_probabilities',
          'attention_weighted_values', 'attention_output', 'residual1', 'norm1',
          'ffn_fc1', 'gelu', 'ffn_fc2', 'residual2', 'output']
COUNTS = [6336, 6336, 6336, 9801, 9801, 6336, 6336, 6336, 6336, 25344, 25344, 6336, 6336, 6336]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = ROOT / 'build/encoder/vectors'
    out.mkdir(parents=True, exist_ok=True)
    model = FixedKWT(ROOT / 'models/kwt1_fixed16_v1', backend='int64')
    configs = []
    ops = ['attention.q', 'attention.k', 'attention.v', 'attention.output', 'ffn.fc1', 'ffn.fc2']
    expected_offsets = [(0, 8192), (8704, 16896), (17408, 25600), (26112, 34304), (34816, 67584), (69632, 102400)]
    for layer in model.config['layers']:
        words = []
        for name, offsets in zip(ops, expected_offsets):
            op = layer['dense'][name]
            actual = tuple(model.config['tensors'][op[key]]['offset_bytes'] for key in ['kernel', 'bias'])
            if actual != offsets:
                raise ValueError('Parameter layout differs from encoder RTL.')
            words.append(op['input_f'] + op['weight_f'] - op['output_f'])
        words += [layer[k] for k in ['input_f', 'q_f', 'k_f', 'v_f', 'attention_weighted_values_f',
                                    'attention_output_f', 'residual1_f', 'norm1_f', 'ffn_fc1_f',
                                    'gelu_f', 'ffn_fc2_f', 'residual2_f', 'output_f']]
        words += [layer['norm'][n][k] for n in ['norm1', 'norm2'] for k in ['gamma_f', 'beta_f']]
        for key in ['residual1_f', 'residual2_f']:
            # Exact rearrangement of the model's constant epsilon expression.
            epsilon_add = (1 << (34 + 2 * layer[key])) // 1000000
            words += [(epsilon_add >> (16 * w)) & 65535 for w in range(4)]
        words += [0]
        assert len(words) == 32
        configs.append(words)
    np.asarray(configs, dtype='<i2').tofile(out / 'configs.bin')
    for kind in ['exp', 'gelu']:
        model.parameters['lut.' + kind].astype('<u4').tofile(out / (kind + '.bin'))
    rows = [json.loads(line) for line in (ROOT / 'data/reference/golden_validation24/samples.jsonl').read_text().splitlines()]
    selected = []
    for label in range(12):
        row = next(row for row in rows if row['label_index'] == label)
        stored = np.load(ROOT / 'data/reference/golden_validation24' / (row['sample_id'] + '.npz'))
        selected.append((encode(stored['encoder_input'], model.config['encoder_input_f']),
                         {'sample_id': row['sample_id'], 'label_index': label, 'source': 'validation'}))
    rng = np.random.default_rng(20261021)
    selected += [(np.zeros((99, 64), dtype='<i2'), {'source': 'zeros'}),
                 (rng.integers(-32768, 32768, (99, 64), dtype=np.int16), {'source': 'new_full_range_random'})]
    cases = []
    for index, (x, metadata) in enumerate(selected):
        y, trace = model.encoder(x, encoded=True, trace=True)
        prefix = out / f'task_{index:02d}'
        x.astype('<i2').tofile(str(prefix) + '_input.bin')
        y.astype('<i2').tofile(str(prefix) + '_expected.bin')
        with open(str(prefix) + '_trace.bin', 'wb') as stream:
            for layer in range(12):
                for stage, count in zip(STAGES, COUNTS):
                    values = trace[f'layer_{layer:02d}_{stage}']
                    assert values.size == count
                    stream.write(values.astype('<i8').tobytes())
        cases.append({'index': index, **metadata})
        print('Prepared encoder task', index, metadata, flush=True)
    # Independent scalar divider and wide-sqrt boundary cases.
    divs = [(n, d) for n in [-9223372036854775807, -65537, -5, -3, -1, 0, 1, 3, 5, 65537,
                              9223372036854775807] for d in [1, 2, 3, 65536, 1 << 40]]
    divs += [(int(rng.integers(-(1 << 53), 1 << 53)), int(rng.integers(1, 1 << 40))) for _ in range(96)]
    with (out / 'div_vectors.txt').open('w') as stream:
        for n, d in divs:
            # Python integer oracle avoids int64 remainder*2 overflow in extreme cases.
            q, r = divmod(n, d)
            expected = q + int(2 * r > d or (2 * r == d and q & 1))
            if abs(n) < 1 << 53:
                assert expected == int(round_divide(n, d))
            stream.write(f'{n & ((1 << 64)-1):016x} {d:016x} {expected & ((1 << 64)-1):016x}\n')
    sqrts = [0, 1, 2, 3, 4, 15, 16, 17, (1 << 128)-1]
    sqrts += [v for bits in [16, 32, 48, 64, 66, 80, 100, 126] for v in [(1 << bits)-1, 1 << bits, (1 << bits)+1]]
    sqrts += [int.from_bytes(rng.bytes(16), 'little') for _ in range(96)]
    with (out / 'sqrt_vectors.txt').open('w') as stream:
        for n in sqrts:
            stream.write(f'{n:032x} {isqrt(n):016x}\n')
    result = {'parameter_manifest_sha256': digest(model.directory / 'manifest.json'),
              'tasks': cases, 'stages': STAGES, 'stage_elements': COUNTS,
              'trace_elements_per_task': 12 * sum(COUNTS), 'div_cases': len(divs), 'sqrt_cases': len(sqrts),
              'not_official_evaluation': True, 'reference_answers_loaded_into_rtl': False,
              'files': {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file() and p.name != 'manifest.json'}}
    (out / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
