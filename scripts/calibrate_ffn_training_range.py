"""Channel ranges from the whole training split, with the existing 1.25 headroom."""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.ffn_channel import ChannelFFN
from sim.fixed_ops import encode
from ablate_ffn_scales import OUT, PACKAGES, CALIBRATION, range_f, write_json, records


def ranges():
    from sim.kwt_reference import KWTReference
    rows = records('training')
    assert all(row['split'] == 'training' for row in rows)
    policy = {'source_split': 'training', 'expected_samples': len(rows),
              'activation_margin': 1.25, 'output_selection': 'range based, no deliberate clipping search',
              'reason': 'initial 240-sample SSE optimization overfit rare output tails',
              'validation_used_to_set_ranges': False, 'test_used': False}
    write_json(OUT / 'training-range-policy.json', policy)
    xmax, ymax = np.zeros((12, 64)), np.zeros((12, 256))
    reference = KWTReference()
    start = time.perf_counter()
    for i, row in enumerate(rows):
        x, y = reference.infer_ffn_reference(reference.load_audio(row))
        xmax = np.maximum(xmax, np.abs(x).max(axis=1))
        ymax = np.maximum(ymax, np.abs(y).max(axis=1))
        if (i + 1) % 1000 == 0 or i + 1 == len(rows):
            result = dict(policy, status='completed' if i + 1 == len(rows) else 'running',
                          samples=i + 1, input_max=xmax.tolist(), output_max=ymax.tolist(),
                          elapsed_seconds=time.perf_counter() - start)
            write_json(OUT / 'training-full-ranges.json', result)
            print('full training ranges %d/%d %.1fs' % (i + 1, len(rows), result['elapsed_seconds']), flush=True)
    reference.close()


def convert():
    ranges = json.loads((OUT / 'training-full-ranges.json').read_text())
    assert ranges['status'] == 'completed' and ranges['source_split'] == 'training'
    old = ChannelFFN(ROOT / 'models/kwt1_ffn_channel_v1')
    weights = np.load(ROOT / 'models/kwt1_float32/parameters_float32.npz')
    for name in ['Q1_training_range', 'Q2_training_range']:
        directory = PACKAGES / name
        directory.mkdir(parents=True, exist_ok=True)
        manifest = dict(old.config, format='kwt-ffn-channel16-v2', variant=name, layers=[],
                        calibration_source='whole training split; original actual/synthetic records',
                        calibration_samples=ranges['samples'], range_margin=1.25,
                        validation_used_to_set_ranges=False, test_used=False,
                        activation_scales='per-channel whole-training extrema, 1.25 headroom',
                        weight_scales='column scales from checkpoint' if name == 'Q1_training_range' else
                                      'joint input/output exponents; no checkpoint weight clipping',
                        output_scales='per-column training extrema with headroom, no clipping objective')
        for layer in range(12):
            cfg = old.config['layers'][layer]
            prefix = 'encoder.%02d.ffn.fc1.' % layer
            w = weights[prefix + 'kernel'].astype(np.float64)
            if name == 'Q1_training_range':
                fi = np.full(64, cfg['input_f'], dtype=np.int32)
                a = cfg['input_f'] + np.asarray(cfg['weight_f'])
                kernel, bias = old.parameters[layer]['kernel'], old.parameters[layer]['bias']
            else:
                fi = range_f(np.asarray(ranges['input_max'][layer]), 1.25)
                a = np.floor(np.log2(32767.0 / np.abs(w * np.exp2(-fi[:, None])).max(axis=0))).astype(np.int32)
                kernel = encode(w, a[None, :] - fi[:, None])
                bias = np.rint(weights[prefix + 'bias'].astype(np.float64) * np.exp2(a)).astype('<i8')
            fo = range_f(np.asarray(ranges['output_max'][layer]), 1.25)
            shifts = (a - fo).astype('i1')
            assert int(shifts.min()) >= -30 and int(shifts.max()) <= 62
            packed = shifts.view('u1').reshape(128, 2).astype('<u2')
            shift_words = (packed[:, 0] | (packed[:, 1] << 8)).astype('<u2')
            np.savez(directory / ('layer_%02d.npz' % layer), kernel=kernel, bias=bias,
                     shifts=shifts, shift_words=shift_words)
            blob = kernel.astype('<i2').tobytes() + bias.astype('<i8').tobytes() + shift_words.tobytes()
            (directory / ('layer_%02d.bin' % layer)).write_bytes(blob)
            (directory / ('layer_%02d.hex' % layer)).write_text(''.join('%04x\n' % int(v)
                                                         for v in np.frombuffer(blob, dtype='<u2')))
            manifest['layers'].append(dict(cfg, input_f=fi.tolist(), output_f=fo.tolist(),
                                          accumulator_f=a.tolist(),
                                          weight_f=(a[None, :] - fi[:, None]).tolist()))
        write_json(directory / 'manifest.json', manifest)
        print('TRAINING_RANGE_PACKAGE_FROZEN ' + name, flush=True)
    x_all = np.load(CALIBRATION / 'inputs.npy', mmap_mode='r')
    y_all = np.load(CALIBRATION / 'outputs.npy', mmap_mode='r')
    scores = {}
    for name, directory in [('baseline', ROOT / 'models/kwt1_ffn_channel_v1'),
                            ('Q1_training_range', PACKAGES / 'Q1_training_range'),
                            ('Q2_training_range', PACKAGES / 'Q2_training_range')]:
        model = ChannelFFN(directory)
        errors = []
        for layer in range(12):
            x = np.asarray(x_all[:, layer]).reshape(-1, 64)
            y = np.asarray(y_all[:, layer], dtype=np.float64).reshape(-1, 256)
            actual = model.decode_ffn(model.ffn(x, layer), layer)
            errors.append(float(np.sqrt(np.sum((actual - y) ** 2) / np.sum(y * y))))
        scores[name] = {'per_layer_nrmse': errors, 'max_layer_nrmse': max(errors)}
    selection = {'rule': 'smallest maximum layer NRMSE on the original 240 training calibration records',
                 'ranges_source': 'all training records', 'scores': scores,
                 'selected_variant': min(scores, key=lambda name: scores[name]['max_layer_nrmse']),
                 'frozen_before_validation': True, 'validation_used_for_selection': False}
    write_json(OUT / 'training-range-selection.json', selection)
    print('TRAIN_SELECTED ' + selection['selected_variant'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['ranges', 'convert'])
    args = parser.parse_args()
    {'ranges': ranges, 'convert': convert}[args.stage]()
