"""Pinned upstream KWT-1 float32 inference and intermediate tensor access.

The model remains in TensorFlow graph mode, as required by its original loader.
All exported tensors are single-sample, batch-one inference results.
"""

import json
import hashlib
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'third_party' / 'keyword-transformer'
DATASET = ROOT / 'data' / 'speech_commands_v0.02'
COMMIT = '237e4097afd4f6851e0b82f0a8d65c2dfe8eae30'


def load_waveform(record):
    """Independent PCM decoder for verification only; export uses upstream code."""
    audio = np.zeros(16000, dtype=np.float32)
    if not record['synthetic_silence']:
        with wave.open(str(DATASET / record['relative_path']), 'rb') as stream:
            if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
                raise ValueError(f'Unsupported WAV format: {record["relative_path"]}')
            pcm = np.frombuffer(stream.readframes(16000), dtype='<i2')
        audio[:len(pcm)] = pcm.astype(np.float32) / np.float32(32768.0)
    return audio.reshape(1, 16000)


class KWTReference:
    def __init__(self):
        import tensorflow as tf
        import tensorflow_addons as tfa
        from tensorflow.core.protobuf import trackable_object_graph_pb2

        sys.path.insert(0, str(UPSTREAM))
        from kws_streaming.models import models as model_registry
        from kws_streaming.models.transformer_utils import KWSTransformer

        contract = json.loads((ROOT / 'constraints/competition_contract.json').read_text(encoding='utf-8'))
        commit = subprocess.check_output(['git', '-C', str(UPSTREAM), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(UPSTREAM), 'status', '--porcelain',
                                         '--untracked-files=no'], text=True).strip()
        if commit != contract['upstream_commit'] or dirty:
            raise ValueError('Competition source commit mismatch or upstream tracked files changed.')
        pdf = ROOT / contract['source_pdf']
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != contract['source_pdf_sha256']:
            raise ValueError('The controlling competition PDF changed; review the contract first.')
        self.contract = contract
        self.tf = tf
        self.tfa_version = tfa.__version__
        tf.compat.v1.reset_default_graph()
        tf.random.set_seed(2026)
        self.session = tf.compat.v1.Session(config=tf.compat.v1.ConfigProto(
            intra_op_parallelism_threads=4, inter_op_parallelism_threads=2,
            device_count={'GPU': 0}))
        tf.compat.v1.keras.backend.set_session(self.session)
        tf.keras.backend.set_learning_phase(0)
        directory = UPSTREAM / 'models_data_v2_12_labels' / 'kwt1'
        flags = json.loads((directory / 'flags.json').read_text(encoding='utf-8'))
        flags.update(batch_size=1, training=False, train=0, prenorm=False,
                     approximate_gelu=False, distill_teacher_json=None,
                     use_spec_augment=0, use_spec_cutout=0, time_shift_ms=0.0,
                     resample=0.0, sp_resample=0.0, sp_time_shift_ms=0.0,
                     data_dir=str(DATASET), data_url='')
        for key, expected in contract['model_flags'].items():
            if flags.get(key) != expected:
                raise ValueError(f'Competition configuration mismatch: {key}')
        for filename, expected in contract['checkpoint_sha256'].items():
            if hashlib.sha256((directory / filename).read_bytes()).hexdigest() != expected:
                raise ValueError('Competition checkpoint changed: ' + filename)
        self.flags = SimpleNamespace(**flags)
        self.model = model_registry.MODELS['kws_transformer'](self.flags)
        status = self.model.load_weights(str(directory / 'best_weights'))
        status.assert_existing_objects_matched()
        status.expect_partial()
        reader = tf.train.load_checkpoint(str(directory / 'best_weights'))
        graph = trackable_object_graph_pb2.TrackableObjectGraph()
        graph.ParseFromString(reader.get_tensor('_CHECKPOINTABLE_OBJECT_GRAPH'))
        names = {attribute.full_name: attribute.checkpoint_key
                 for node in graph.nodes for attribute in node.attributes
                 if attribute.name == 'VARIABLE_VALUE'}
        self.checkpoint_mismatches = []
        for variable, value in zip(self.model.weights, self.session.run(self.model.weights)):
            name = variable.name.rsplit(':', 1)[0]
            if name not in names or not np.array_equal(value, reader.get_tensor(names[name])):
                self.checkpoint_mismatches.append(name)
        if self.checkpoint_mismatches:
            raise ValueError(f'Checkpoint variable mismatch: {self.checkpoint_mismatches}')
        self.transformer = next(layer for layer in self.model.layers if isinstance(layer, KWSTransformer))
        self.labels = (directory / 'labels.txt').read_text(encoding='utf-8').splitlines()
        if self.labels != contract['labels']:
            raise ValueError('Competition checkpoint label mapping changed.')
        self._build_trace()

    def _build_trace(self):
        """Reuse official layers/attention with inference disabled augmentation."""
        tf, transformer = self.tf, self.transformer
        mfcc = self.model.layers[1].output
        projection = transformer.patch_proj(mfcc)
        tokens = tf.concat([tf.broadcast_to(transformer.class_emb, (1, 1, 64)), projection], axis=1)
        x = tokens + transformer.pos_emb
        trace = {'mfcc': mfcc, 'input_projection': projection, 'encoder_input': x}
        layer_outputs = []
        ffn_inputs = []
        ffn_outputs = []
        for index, layer in enumerate(transformer.enc_layers):
            prefix = f'layer_{index:02d}_'
            attention = layer.att
            q = attention.separate_heads(attention.query_dense(x), 1)
            k = attention.separate_heads(attention.key_dense(x), 1)
            v = attention.separate_heads(attention.value_dense(x), 1)
            weighted, probabilities = attention.attention(q, k, v)
            concatenated = tf.reshape(tf.transpose(weighted, (0, 2, 1, 3)), (1, 99, 64))
            projected = attention.combine_heads(concatenated)
            attn_output = layer.dropout1(projected, training=False)
            residual1 = x + attn_output
            norm1 = layer.layernorm1(residual1)
            fc1 = layer.ffn.layers[0](norm1)
            gelu = layer.ffn.layers[1](fc1)
            fc2 = layer.ffn.layers[2](gelu)
            residual2 = norm1 + layer.dropout2(fc2, training=False)
            y = layer.layernorm2(residual2)
            score = tf.matmul(q, k, transpose_b=True)
            values = {'input': x, 'q': q[:, 0], 'k': k[:, 0], 'v': v[:, 0],
                      'qk_scores': score[:, 0], 'scaled_scores': score[:, 0] / 8.0,
                      'attention_probabilities': probabilities[:, 0],
                      'attention_weighted_values': concatenated, 'attention_output': attn_output,
                      'residual1': residual1, 'norm1': norm1, 'ffn_fc1': fc1,
                      'gelu': gelu, 'ffn_fc2': fc2, 'residual2': residual2, 'output': y}
            trace.update({prefix + name: value for name, value in values.items()})
            layer_outputs.append(y)
            ffn_inputs.append(norm1)
            ffn_outputs.append(fc1)
            x = y
        logits = self.model.layers[-1](x[:, 0], training=False)
        trace.update(encoder_output=x, logits=logits)
        self.trace_fetches = trace
        self.basic_fetches = {'mfcc': mfcc, 'encoder_input': trace['encoder_input'],
                              'encoder_output': x, 'encoder_layers': tf.stack(layer_outputs, axis=1),
                              'logits': logits}
        self.ffn_inputs = tf.stack(ffn_inputs, axis=1)
        self.ffn_outputs = tf.stack(ffn_outputs, axis=1)
        self.official_logits = self.model.outputs[0]

    def infer_ffn_reference(self, audio):
        """Return all twelve true norm1 inputs and first-linear outputs, batch removed."""
        inputs, outputs = self.session.run([self.ffn_inputs, self.ffn_outputs],
                                           feed_dict={self.model.inputs[0]: audio})
        return inputs[0], outputs[0]

    def classify_encoder(self, values):
        """Use the actual original software classifier on decoded encoder outputs."""
        if not hasattr(self, '_classifier_input'):
            self._classifier_input = self.tf.compat.v1.placeholder(self.tf.float32, [None, 99, 64])
            self._classifier_logits = self.model.layers[-1](self._classifier_input[:, 0], training=False)
        return self.session.run(self._classifier_logits, feed_dict={self._classifier_input: values})

    def infer(self, audio, detailed=False, compare_original=False):
        """Return unbatched float32 arrays for a (1,16000) waveform."""
        fetches = dict(self.trace_fetches if detailed else self.basic_fetches)
        if compare_original:
            fetches['official_logits'] = self.official_logits
        values = self.session.run(fetches, feed_dict={self.model.inputs[0]: audio})
        result = {name: value[0].astype('<f4', copy=False) for name, value in values.items()}
        for name, value in result.items():
            if not np.isfinite(value).all():
                raise ValueError(f'Non-finite reference tensor: {name}')
        return result

    def load_audio(self, record):
        """Use pinned AudioProcessor graph for actual export, with no augmentation."""
        from kws_streaming.data import input_data

        if record['synthetic_silence']:
            return np.zeros((1, 16000), dtype=np.float32)
        if not hasattr(self, '_audio_processor'):
            processor = object.__new__(input_data.AudioProcessor)
            processor.prepare_processing_graph(self.flags)
            self._audio_processor = processor
        processor = self._audio_processor
        feed = {processor.wav_filename_placeholder_: str(DATASET / record['relative_path']),
                processor.foreground_volume_placeholder_: 1.0,
                processor.foreground_resampling_placeholder_: 1.0,
                processor.time_shift_padding_placeholder_: [[0, 0], [0, 0]],
                processor.time_shift_offset_placeholder_: [0, 0],
                processor.background_data_placeholder_: np.zeros((16000, 1), np.float32),
                processor.background_volume_placeholder_: 0.0}
        official_audio = self.session.run(processor.output_, feed_dict=feed).reshape(1, 16000)
        return official_audio

    def compare_official_preprocessing(self, record):
        """Independently verify PCM decoding/padding against the upstream graph."""
        official_audio = self.load_audio(record)
        ours = load_waveform(record)
        if not np.array_equal(official_audio, ours):
            raise ValueError(f'PCM preprocessing differs from upstream: {record["sample_id"]}')
        return float(np.max(np.abs(official_audio - ours)))

    def export_parameters(self, directory):
        """Export 162 trained float32 variables with semantic names and shapes."""
        directory.mkdir(parents=True, exist_ok=True)
        transformer = self.transformer
        variables = {'embedding.pos': transformer.pos_emb, 'embedding.class': transformer.class_emb,
                     'embedding.projection.kernel': transformer.patch_proj.kernel,
                     'embedding.projection.bias': transformer.patch_proj.bias}
        for index, layer in enumerate(transformer.enc_layers):
            prefix = f'encoder.{index:02d}.'
            variables.update({prefix + 'attention.q.kernel': layer.att.query_dense.kernel,
                              prefix + 'attention.k.kernel': layer.att.key_dense.kernel,
                              prefix + 'attention.v.kernel': layer.att.value_dense.kernel,
                              prefix + 'attention.output.kernel': layer.att.combine_heads.kernel,
                              prefix + 'attention.output.bias': layer.att.combine_heads.bias,
                              prefix + 'norm1.gamma': layer.layernorm1.gamma,
                              prefix + 'norm1.beta': layer.layernorm1.beta,
                              prefix + 'ffn.fc1.kernel': layer.ffn.layers[0].kernel,
                              prefix + 'ffn.fc1.bias': layer.ffn.layers[0].bias,
                              prefix + 'ffn.fc2.kernel': layer.ffn.layers[2].kernel,
                              prefix + 'ffn.fc2.bias': layer.ffn.layers[2].bias,
                              prefix + 'norm2.gamma': layer.layernorm2.gamma,
                              prefix + 'norm2.beta': layer.layernorm2.beta})
        head = self.model.layers[-1].layers[0]
        variables.update({'classifier.kernel': head.kernel, 'classifier.bias': head.bias})
        arrays = self.session.run(variables)
        np.savez(directory / 'parameters_float32.npz', **arrays)
        records = [{'key': name, 'upstream_variable': variables[name].name,
                    'shape': list(value.shape), 'dtype': str(value.dtype), 'elements': int(value.size)}
                   for name, value in arrays.items()]
        manifest = {'upstream_commit': COMMIT, 'variables': records,
                    'variable_count': len(records), 'parameter_count': self.model.count_params(),
                    'checkpoint_variable_values_verified': True,
                    'layernorm_epsilon': 1e-6, 'attention_scale': 0.125,
                    'gelu_approximate': False, 'normalization': 'PostNorm',
                    'classifier': 'class token index 0; no mean pooling', 'labels': self.labels}
        checkpoint_dir = UPSTREAM / 'models_data_v2_12_labels/kwt1'
        manifest['checkpoint_files_sha256'] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(checkpoint_dir.glob('best_weights*'))}
        (directory / 'inference_flags.json').write_text(
            json.dumps(vars(self.flags), indent=2), encoding='utf-8')
        (directory / 'parameters.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return manifest

    def close(self):
        self.session.close()
