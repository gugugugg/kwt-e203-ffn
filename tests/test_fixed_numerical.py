"""Independent arithmetic oracles, boundary cases and real fixed-checkpoint tasks."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

from sim.fixed_ops import dense, encode, exact_dot, gelu, layer_norm, residual, round_divide, round_shift, saturate16, softmax
from sim.kwt_fixed import FixedKWT

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'models/kwt1_fixed16_v1'


def test_signed_ties_even_and_exact_division():
    values = np.arange(-33, 34, dtype=np.int64)
    for shift in [1, 2, 3]:
        expected = [round(int(value) / (2 ** shift)) for value in values]
        np.testing.assert_array_equal(round_shift(values, shift), expected)
    for divisor in [2, 3, 7, 8]:
        expected = [round(int(value) / divisor) for value in values]
        np.testing.assert_array_equal(round_divide(values, divisor), expected)


def test_saturation_and_bias_added_before_rounding():
    np.testing.assert_array_equal(saturate16([-99999, -32768, 32767, 99999]), [-32768, -32768, 32767, 32767])
    # (1*1 + 1)/2 = 1; independently rounding dot/2 first would produce zero.
    actual = dense(np.array([[1]], np.int16), np.array([[1]], np.int16), np.array([1], np.int64), 1, 0, 0, 'int64')
    assert int(actual[0, 0]) == 1


def test_64_dot_extreme_values_against_python_integer_oracle():
    a = np.array([[-32768, 32767] * 32, [32767] * 64], dtype=np.int16)
    b = np.array([[32767, -32768, i - 32] for i in range(64)], dtype=np.int16)
    expected = np.array([[sum(int(a[row, i]) * int(b[i, col]) for i in range(64))
                          for col in range(3)] for row in range(2)], dtype=np.int64)
    assert np.max(np.abs(expected)) > 2 ** 31
    for backend in ['int64', 'exact-f64']:
        np.testing.assert_array_equal(exact_dot(a, b, backend), expected)
    with pytest.raises(OverflowError):
        exact_dot(np.array([[2 ** 53]], dtype=np.int64), np.array([[2]], dtype=np.int64), 'exact-f64')


def test_layernorm_constant_input_and_epsilon_path():
    model = FixedKWT(PACKAGE)
    layer = model.config['layers'][0]
    p = layer['norm']['norm1']
    x = np.full((99, 64), 123, dtype=np.int16)
    actual = layer_norm(x, layer['residual1_f'], model.parameters[p['gamma']], p['gamma_f'],
                        model.parameters[p['beta']], p['beta_f'], layer['norm1_f'])
    expected = saturate16(round_shift(model.parameters[p['beta']], p['beta_f'] - layer['norm1_f']))
    np.testing.assert_array_equal(actual, np.broadcast_to(expected, actual.shape))
    assert np.isfinite(actual).all()


def test_softmax_max_subtraction_and_equal_rows():
    model = FixedKWT(PACKAGE)
    scores = np.zeros((99, 99), dtype=np.int64)
    expected = np.full((99, 99), round(32768 / 99), dtype=np.uint16)
    np.testing.assert_array_equal(softmax(scores, 20, model.parameters['lut.exp']), expected)
    np.testing.assert_array_equal(softmax(scores + 2 ** 40, 20, model.parameters['lut.exp']), expected)
    scores[:, 0] = 100 << 20
    onehot = softmax(scores, 20, model.parameters['lut.exp'])
    assert np.all(onehot[:, 0] == 32768) and np.all(onehot[:, 1:] == 0)


def test_gelu_tail_and_residual_scale_alignment():
    model = FixedKWT(PACKAGE)
    x = np.array([-9 * 1024, 0, 9 * 1024], dtype=np.int16)
    np.testing.assert_array_equal(gelu(x, 10, 10, model.parameters['lut.gelu']), [0, 0, 9 * 1024])
    np.testing.assert_array_equal(residual(np.array([1], np.int16), 1, np.array([1], np.int16), 2, 2), [3])


def test_package_binary_hex_layout_and_corruption_detection(tmp_path):
    model = FixedKWT(PACKAGE)
    for filename in [f'layer_{i:02d}.bin' for i in range(12)] + ['nonlinear_luts.bin']:
        words = np.array([int(line, 16) for line in (PACKAGE / filename).with_suffix('.hex').read_text().splitlines()], dtype='<u2')
        assert words.tobytes() == (PACKAGE / filename).read_bytes()
    assert all(value.dtype.kind in 'iu' for value in model.parameters.values())
    bad = tmp_path / 'bad'
    bad.mkdir()
    for path in PACKAGE.glob('*'):
        shutil.copyfile(path, bad / path.name)
    path = bad / 'layer_00.bin'
    content = bytearray(path.read_bytes())
    content[0] ^= 1
    path.write_bytes(content)
    with pytest.raises(ValueError, match='mismatch'):
        FixedKWT(bad)


def test_real_ffn_all_twelve_layers_against_scalar_integer_oracle():
    golden_path = sorted((ROOT / 'data/reference/golden_validation24').glob('*.npz'))[0]
    model = FixedKWT(PACKAGE)
    with np.load(golden_path) as golden:
        for i in range(12):
            layer = model.config['layers'][i]
            x = encode(golden[f'layer_{i:02d}_norm1'], layer['norm1_f'])
            result = model.ffn(x, i, encoded=True)
            op = layer['dense']['ffn.fc1']
            for row, col in [(0, 0), (42, 127), (98, 255)]:
                acc = sum(int(x[row, j]) * int(model.parameters[op['kernel']][j, col]) for j in range(64))
                acc += int(model.parameters[op['bias']][col])
                shift = op['input_f'] + op['weight_f'] - op['output_f']
                quotient, remainder = divmod(acc, 2 ** shift)
                if remainder * 2 > 2 ** shift or (remainder * 2 == 2 ** shift and quotient % 2):
                    quotient += 1
                assert int(result[row, col]) == max(-32768, min(32767, quotient))


def test_reset_free_repeated_and_continuous_tasks():
    with np.load(sorted((ROOT / 'data/reference/golden_validation24').glob('*.npz'))[0]) as golden:
        real = golden['encoder_input']
    model = FixedKWT(PACKAGE, backend='exact-f64')
    before = model.encoder(real)
    model.encoder(np.zeros((99, 64), np.float32))
    after = model.encoder(real)
    np.testing.assert_array_equal(before, after)
    with pytest.raises(ValueError):
        model.ffn(real, 12)
    with pytest.raises(ValueError):
        model.ffn(np.zeros((64, 99)), 0)
    with pytest.raises(ValueError):
        model.encoder(np.full((99, 64), np.nan))


def test_calibration_provenance_is_training_only():
    config = json.loads((PACKAGE / 'manifest.json').read_text())
    assert config['calibration_split'] == 'training'
    assert not config['validation_or_test_used_to_select_scales']
    rows = [json.loads(line) for line in (ROOT / 'data/manifests/calibration_train240.jsonl').read_text().splitlines()]
    assert len(rows) == 240 and all(row['split'] == 'training' for row in rows)


def test_public_ffn_file_interface_encode_compute_decode(tmp_path):
    model = FixedKWT(PACKAGE)
    layer = 11
    x = np.zeros((99, 64), dtype=np.float32)
    x[0, 0], x[-1, -1] = 0.75, -0.25
    source = tmp_path / 'input.npy'
    np.save(source, x)
    cli = [sys.executable, str(ROOT / 'scripts/run_numerical.py')]
    encoded, calculated, decoded = [tmp_path / name for name in ['input.bin', 'output.bin', 'decoded.npy']]
    subprocess.run(cli + ['--mode', 'encode-input', '--boundary', 'ffn', '--layer', str(layer),
                          '--input', str(source), '--output', str(encoded)], check=True, capture_output=True)
    subprocess.run(cli + ['--mode', 'ffn', '--layer', str(layer), '--encoded',
                          '--input', str(encoded), '--output', str(calculated)], check=True, capture_output=True)
    subprocess.run(cli + ['--mode', 'decode-output', '--boundary', 'ffn', '--layer', str(layer),
                          '--input', str(calculated), '--output', str(decoded)], check=True, capture_output=True)
    codes = model.ffn(x, layer)
    np.testing.assert_array_equal(np.fromfile(calculated, dtype='<i2').reshape(99, 256), codes)
    np.testing.assert_array_equal(np.load(decoded), model.decode_ffn(codes, layer))
    assert json.loads(calculated.with_suffix('.bin.json').read_text())['boundary'] == 'ffn'
