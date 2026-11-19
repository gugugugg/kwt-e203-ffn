"""Train-only scale conversion and independent undergraduate FFN evaluation."""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.ffn_channel import ChannelFFN
from sim.fixed_ops import encode, exact_dot, round_shift, saturate16

OUT = ROOT / 'reports/optimization/quantization'
PACKAGES = ROOT / 'models/ffn_scale_ablation'
CALIBRATION = ROOT / 'data/reference/ffn_calibration_train240'
VARIANTS = ['baseline', 'Q1_output_channel', 'Q2_joint_channel']


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def records(name):
    return [json.loads(s) for s in (ROOT / 'data/manifests' / (name + '.jsonl')).read_text().splitlines()]


def prepare():
    from sim.kwt_reference import KWTReference
    rows = records('calibration_train240')
    assert all(r['split'] == 'training' for r in rows)
    CALIBRATION.mkdir(parents=True, exist_ok=True)
    inputs = np.lib.format.open_memmap(CALIBRATION / 'inputs.npy', mode='w+', dtype='<f4',
                                      shape=(len(rows), 12, 99, 64))
    outputs = np.lib.format.open_memmap(CALIBRATION / 'outputs.npy', mode='w+', dtype='<f4',
                                       shape=(len(rows), 12, 99, 256))
    reference = KWTReference()
    start = time.perf_counter()
    for i, row in enumerate(rows):
        inputs[i], outputs[i] = reference.infer_ffn_reference(reference.load_audio(row))
        if (i + 1) % 40 == 0:
            print('training reference %d/%d' % (i + 1, len(rows)), flush=True)
    reference.close()
    inputs.flush()
    outputs.flush()
    write_json(CALIBRATION / 'manifest.json', {
        'split': 'training', 'samples': len(rows), 'source': 'calibration_train240.jsonl',
        'sample_ids': [r['sample_id'] for r in rows],
        'reference': 'pinned upstream inference, true norm1 and ffn.fc1',
        'elapsed_seconds': time.perf_counter() - start})


def range_f(maximum, margin):
    return np.clip(np.floor(np.log2(32767.0 / np.maximum(maximum * margin, 1e-30))), 0, 24).astype(np.int32)


def calibrate():
    x_all = np.load(CALIBRATION / 'inputs.npy', mmap_mode='r')
    y_all = np.load(CALIBRATION / 'outputs.npy', mmap_mode='r')
    source = json.loads((CALIBRATION / 'manifest.json').read_text())
    assert source['split'] == 'training'
    old = ChannelFFN(ROOT / 'models/kwt1_ffn_channel_v1')
    float_weights = np.load(ROOT / 'models/kwt1_float32/parameters_float32.npz')
    policy = {
        'scope': 'undergraduate first FFN linear, all twelve layers',
        'calibration': 'frozen 240 training samples only', 'test_used': False,
        'input_range_margin': 1.25,
        'weight_policy': 'largest column accumulator exponent with no checkpoint weight clipping',
        'output_candidates': 'Fo=12 plus training per-column margin-1.25 range exponent and its next two exponents',
        'selection': 'minimum actual encoded output SSE against training float reference, per output column',
        'variants': VARIANTS,
        'checkpoint': 'unchanged; no training, fine tuning, distillation or operator changes',
        'hardware': 'same 64x256 int16 kernel, 256 int64 biases and 256 int8 shifts'}
    write_json(OUT / 'calibration-policy.json', policy)
    manifests = {name: dict(old.config, format='kwt-ffn-channel16-v2', layers=[],
                            activation_scales='240-sample training output SSE selection; input policy per variant',
                            weight_scales='column scales from checkpoint' if name == 'Q1_output_channel' else
                                          'joint input/output exponents; no checkpoint weight clipping',
                            calibration_policy=policy, variant=name)
                 for name in VARIANTS[1:]}
    metrics = {name: [] for name in VARIANTS}
    for layer in range(12):
        x = np.asarray(x_all[:, layer], dtype=np.float64).reshape(-1, 64)
        y = np.asarray(y_all[:, layer], dtype=np.float64).reshape(-1, 256)
        prefix = 'encoder.%02d.ffn.fc1.' % layer
        w = float_weights[prefix + 'kernel'].astype(np.float64)
        bias = float_weights[prefix + 'bias'].astype(np.float64)
        ref_sse = float(np.sum(y * y))
        baseline_codes = old.ffn(x, layer)
        baseline_sse = float(np.sum((old.decode_ffn(baseline_codes, layer) - y) ** 2))
        metrics['baseline'].append({'layer': layer, 'nrmse': float(np.sqrt(baseline_sse / ref_sse))})
        output_range = range_f(np.abs(y).max(axis=0), 1.25)
        for name in VARIANTS[1:]:
            cfg = old.config['layers'][layer]
            if name == 'Q1_output_channel':
                fi = np.full(64, cfg['input_f'], dtype=np.int32)
                kernel = old.parameters[layer]['kernel']
                acc_f = cfg['input_f'] + np.asarray(cfg['weight_f'])
                bias_q = old.parameters[layer]['bias']
            else:
                fi = range_f(np.abs(x).max(axis=0), 1.25)
                scaled_w = w * np.exp2(-fi[:, None])
                acc_f = np.floor(np.log2(32767.0 / np.abs(scaled_w).max(axis=0))).astype(np.int32)
                kernel = encode(w, acc_f[None, :] - fi[:, None])
                bias_q = np.rint(bias * np.exp2(acc_f)).astype('<i8')
            input_q = encode(x, fi)
            acc = exact_dot(input_q, kernel, 'exact-f64') + bias_q
            best_error = np.full(256, np.inf)
            best_fo = np.full(256, 12, dtype=np.int32)
            for fo in [np.full(256, 12), output_range, np.minimum(output_range + 1, 24),
                       np.minimum(output_range + 2, 24)]:
                shifts = acc_f - fo
                quantized = np.empty_like(acc)
                for shift in np.unique(shifts):
                    columns = shifts == shift
                    quantized[:, columns] = round_shift(acc[:, columns], int(shift))
                decoded = saturate16(quantized).astype(np.float64) * np.exp2(-fo)
                error = np.sum((decoded - y) ** 2, axis=0)
                selected = error < best_error
                best_error[selected], best_fo[selected] = error[selected], fo[selected]
            shifts = (acc_f - best_fo).astype('i1')
            assert int(shifts.min()) >= -30 and int(shifts.max()) <= 62
            packed = shifts.view('u1').reshape(128, 2).astype('<u2')
            shift_words = (packed[:, 0] | (packed[:, 1] << 8)).astype('<u2')
            directory = PACKAGES / name
            directory.mkdir(parents=True, exist_ok=True)
            np.savez(directory / ('layer_%02d.npz' % layer), kernel=kernel, bias=bias_q,
                     shifts=shifts, shift_words=shift_words)
            blob = kernel.astype('<i2').tobytes() + bias_q.astype('<i8').tobytes() + shift_words.tobytes()
            (directory / ('layer_%02d.bin' % layer)).write_bytes(blob)
            (directory / ('layer_%02d.hex' % layer)).write_text(''.join('%04x\n' % int(v)
                                                         for v in np.frombuffer(blob, dtype='<u2')))
            manifests[name]['layers'].append(dict(
                cfg, input_f=fi.tolist(), output_f=best_fo.tolist(), accumulator_f=acc_f.tolist(),
                weight_f=(acc_f[None, :] - fi[:, None]).tolist() if name == 'Q2_joint_channel' else cfg['weight_f']))
            metrics[name].append({'layer': layer, 'nrmse': float(np.sqrt(best_error.sum() / ref_sse)),
                                  'input_f_range': [int(fi.min()), int(fi.max())],
                                  'output_f_range': [int(best_fo.min()), int(best_fo.max())]})
        print('calibrated layer %02d: %s' % (layer, {n: metrics[n][-1]['nrmse'] for n in VARIANTS}), flush=True)
    for name, manifest in manifests.items():
        write_json(PACKAGES / name / 'manifest.json', manifest)
    write_json(OUT / 'training-calibration.json', {'policy': policy, 'metrics': metrics,
                                                 'parameters_frozen_before_validation': True})


def evaluate(report_name='validation.json'):
    from sim.kwt_reference import KWTReference
    rows = records('validation')
    models = {'baseline': ChannelFFN(ROOT / 'models/kwt1_ffn_channel_v1')}
    models.update({n: ChannelFFN(PACKAGES / n) for n in VARIANTS[1:]})
    errors = {n: np.zeros(12) for n in models}
    worst = {n: np.zeros(12) for n in models}
    squares = np.zeros(12)
    reference = KWTReference()
    start = time.perf_counter()
    for i, row in enumerate(rows):
        inputs, outputs = reference.infer_ffn_reference(reference.load_audio(row))
        for layer in range(12):
            y = outputs[layer].astype(np.float64)
            ref = float(np.sum(y * y))
            squares[layer] += ref
            for name, model in models.items():
                codes = model.ffn(inputs[layer], layer)
                actual = model.decode_ffn(codes, layer)
                sse = float(np.sum((actual - y) ** 2))
                errors[name][layer] += sse
                worst[name][layer] = max(worst[name][layer], np.sqrt(sse / y.size) / max(np.sqrt(ref / y.size), 1e-8))
        if (i + 1) % 100 == 0 or i + 1 == len(rows):
            print('frozen Q0/Q1/Q2 validation %d/%d %.1fs' % (i + 1, len(rows), time.perf_counter() - start), flush=True)
    reference.close()
    result = {'samples': len(rows), 'split': 'validation', 'test_used': False,
              'parameters_frozen_before_validation': True, 'variants': {},
              'elapsed_seconds': time.perf_counter() - start}
    for name, model in models.items():
        nrmse = np.sqrt(errors[name] / np.maximum(squares, len(rows) * 99 * 256 * 1e-16))
        result['variants'][name] = {'per_layer_nrmse': nrmse.tolist(),
            'max_layer_nrmse': float(nrmse.max()), 'worst_single_task_per_layer': worst[name].tolist(),
            'saturations': model.stats, 'passes_local_3percent': bool(nrmse.max() <= .03 and worst[name].max() <= .03)}
    write_json(OUT / report_name, result)
    print(json.dumps({n: r['max_layer_nrmse'] for n, r in result['variants'].items()}), flush=True)


def vectors():
    tasks = json.loads((ROOT / 'build/rtl/vectors/manifest.json').read_text())['ffn_tasks']
    for name in VARIANTS[1:]:
        model = ChannelFFN(PACKAGES / name, backend='int64')
        directory = ROOT / 'build/optimization/quantization' / name
        directory.mkdir(parents=True, exist_ok=True)
        rows = []
        for task in tasks[:12]:
            layer = task['layer']
            # Same real floating task as the original baseline; do not rescale the old int16 input.
            # Task manifests reference the detailed golden TensorFlow exports.
            sample_id = sorted((ROOT / 'data/numerical/fixed16_v1/ffn_vectors').glob('*.npz'))[0].stem
            with np.load(ROOT / 'data/reference/golden_validation24' / (sample_id + '.npz')) as source:
                x = source['layer_%02d_norm1' % layer]
            q = encode(x, np.asarray(model.config['layers'][layer]['input_f']))
            y = model.ffn(q, layer, encoded=True)
            for kind, data in [('input', q), ('expected', y)]:
                path = directory / ('linear_%02d_%s.bin' % (task['index'], kind))
                data.astype('<i2').tofile(path)
                path.with_suffix('.hex').write_text(''.join('%04x\n' % int(v) for v in data.view('<u2').flat))
            rows.append({'index': task['index'], 'layer': layer, 'sample_id': sample_id})
        write_json(directory / 'manifest.json', {'tasks': rows, 'reference_backend': 'int64',
                                                'official_performance_tasks': False})
        print('exported %s true-input RTL fixtures' % name, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'calibrate', 'evaluate', 'vectors'])
    parser.add_argument('--variants', nargs='+', default=VARIANTS[1:])
    parser.add_argument('--report', default='validation.json')
    args = parser.parse_args()
    VARIANTS = ['baseline'] + args.variants
    if args.stage == 'evaluate':
        evaluate(args.report)
    else:
        {'prepare': prepare, 'calibrate': calibrate, 'vectors': vectors}[args.stage]()
