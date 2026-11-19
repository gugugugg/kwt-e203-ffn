"""Load the specified upstream checkpoint and run one synthetic inference.

This checks environment/model wiring. It does not measure dataset accuracy.
Run with .venv-reference/Scripts/python.exe.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'third_party' / 'keyword-transformer'
sys.path.insert(0, str(UPSTREAM))
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
os.environ.setdefault('CUDA_VISIBLE_DEVICES', '-1')

def main():
    """Write checkpoint, tensor-shape and finite-output results to a JSON report."""
    import numpy as np
    import tensorflow as tf
    import tensorflow_addons as tfa
    from tensorflow.core.protobuf import trackable_object_graph_pb2
    from kws_streaming.models import models as model_registry
    from kws_streaming.models.transformer_utils import KWSTransformer

    model_dir = UPSTREAM / 'models_data_v2_12_labels' / 'kwt1'
    flags_dict = json.loads((model_dir / 'flags.json').read_text(encoding='utf-8'))
    flags_dict.update(batch_size=1, training=False, train=0, prenorm=False,
                      approximate_gelu=False, distill_teacher_json=None,
                      use_spec_augment=0, use_spec_cutout=0,
                      time_shift_ms=0.0, resample=0.0)
    flags = SimpleNamespace(**flags_dict)
    tf.random.set_seed(2026)
    session = tf.compat.v1.Session(config=tf.compat.v1.ConfigProto(
        intra_op_parallelism_threads=4, inter_op_parallelism_threads=2))
    tf.compat.v1.keras.backend.set_session(session)
    tf.keras.backend.set_learning_phase(0)
    model = model_registry.MODELS['kws_transformer'](flags)
    status = model.load_weights(str(model_dir / 'best_weights'))
    status.assert_existing_objects_matched()
    # The checkpoint also contains training optimizer state, unused for inference.
    status.expect_partial()
    checkpoint = tf.train.load_checkpoint(str(model_dir / 'best_weights'))
    object_graph = trackable_object_graph_pb2.TrackableObjectGraph()
    object_graph.ParseFromString(checkpoint.get_tensor('_CHECKPOINTABLE_OBJECT_GRAPH'))
    checkpoint_names = {attribute.full_name: attribute.checkpoint_key
                        for node in object_graph.nodes for attribute in node.attributes
                        if attribute.name == 'VARIABLE_VALUE'}
    parameter_mismatches = []
    for variable, value in zip(model.weights, session.run(model.weights)):
        name = variable.name.rsplit(':', 1)[0]
        key = checkpoint_names.get(name)
        if key is None or not np.array_equal(value, checkpoint.get_tensor(key)):
            parameter_mismatches.append(name)
    transformer = next(layer for layer in model.layers if isinstance(layer, KWSTransformer))
    waveform = np.zeros((1, 16000), dtype=np.float32)
    feed = {model.inputs[0]: waveform}
    logits = np.asarray(session.run(model.outputs, feed_dict=feed))
    logits = logits.reshape(1, 12)
    mfcc = model.layers[1].output
    projected = transformer.patch_proj(mfcc)
    tokens = tf.concat([tf.broadcast_to(transformer.class_emb, (1, 1, 64)), projected], axis=1)
    encoder_input = tokens + transformer.pos_emb
    encoded = encoder_input
    layer_shapes = []
    for layer in transformer.enc_layers:
        encoded, _ = layer(encoded, training=False)
        layer_shapes.append(list(encoded.shape))
    head = model.layers[-1]
    manual_logits_tensor = head(encoded[:, 0], training=False)
    encoded_value, manual_logits = session.run([encoded, manual_logits_tensor], feed_dict=feed)
    manual_logits = np.asarray(manual_logits).reshape(1, 12)
    repeated_logits = np.asarray(session.run(model.outputs, feed_dict=feed)).reshape(1, 12)
    max_difference = float(np.max(np.abs(logits - manual_logits)))
    repeat_identical = bool(np.array_equal(logits, repeated_logits))
    finite = bool(np.isfinite(logits).all() and np.isfinite(encoded_value).all())
    report = {
        'check': 'checkpoint_and_synthetic_zero_waveform_only',
        'status': 'passed' if finite and repeat_identical and max_difference <= 1e-6
                  and not parameter_mismatches else 'failed',
        'upstream_commit': subprocess.check_output(
            ['git', '-C', str(UPSTREAM), 'rev-parse', 'HEAD'], text=True).strip(),
        'python': sys.version,
        'tensorflow': tf.__version__, 'tensorflow_addons': tfa.__version__, 'numpy': np.__version__,
        'upstream_requested_tensorflow': '2.4.0rc1',
        'runtime_difference': 'Using CPU TensorFlow 2.4.0; official-reference parity not yet measured.',
        'parameters': model.count_params(),
        'checkpoint_existing_model_objects_matched': True,
        'checkpoint_model_variables_compared': len(model.weights),
        'checkpoint_variable_value_mismatches': parameter_mismatches,
        'mfcc_shape': list(mfcc.shape), 'encoder_input_shape': list(encoder_input.shape),
        'encoder_output_shape': list(encoded.shape), 'encoder_layer_shapes': layer_shapes,
        'encoder_layers': len(transformer.enc_layers),
        'prenorm': [bool(layer.prenorm) for layer in transformer.enc_layers],
        'ffn_hidden_dimensions': [int(layer.ffn.layers[0].units) for layer in transformer.enc_layers],
        'class_head_input': 'final_encoder_output[:, 0, :]',
        'logits_shape': list(logits.shape), 'logits': logits.tolist(),
        'finite_outputs': finite, 'repeat_bit_identical': repeat_identical,
        'manual_encoder_path_logit_max_absolute_difference': max_difference,
        'labels': (model_dir / 'labels.txt').read_text(encoding='utf-8').splitlines(),
        'dataset_accuracy_tested': False,
    }
    output_dir = ROOT / 'reports' / 'environment'
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'model-smoke.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    session.close()
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
