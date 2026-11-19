"""Deterministic integer numerical model: undergraduate FFN and optional full encoder."""

import hashlib
import json
from pathlib import Path

import numpy as np

from sim.fixed_ops import decode, dense, encode, exact_dot, gelu, layer_norm, residual, round_shift, saturate16, softmax


class FixedKWT:
    def __init__(self, package, backend='int64'):
        self.directory = Path(package)
        raw = (self.directory / 'manifest.json').read_bytes()
        expected = (self.directory / 'manifest.sha256').read_text().strip()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Converted package manifest hash mismatch.')
        self.config = json.loads(raw)
        if self.config['format'] != 'kwt-fixed16-v1':
            raise ValueError('Unknown numerical format.')
        blobs = {}
        for name, record in self.config['files'].items():
            if not name.endswith('.bin'):
                continue
            blob = (self.directory / name).read_bytes()
            if len(blob) != record['bytes'] or hashlib.sha256(blob).hexdigest() != record['sha256']:
                raise ValueError('Converted parameter file mismatch: ' + name)
            blobs[name] = blob
        self.parameters = {}
        for key, record in self.config['tensors'].items():
            value = np.frombuffer(blobs[record['file']], dtype=record['dtype'],
                                  count=record['elements'], offset=record['offset_bytes']).reshape(record['shape'])
            self.parameters[key] = value
        self.backend = backend
        self.stats = {}

    def _dense(self, x, layer, operation, name):
        op = layer['dense'][operation]
        return dense(x, self.parameters[op['kernel']], self.parameters[op['bias']],
                     op['input_f'], op['weight_f'], op['output_f'], self.backend, self.stats, name)

    def ffn(self, x, layer_index, encoded=False):
        """Undergraduate hardware boundary: 99x64 -> 99x256, first FFN linear only."""
        if not 0 <= layer_index < 12:
            raise ValueError('Layer index must be 0..11.')
        layer = self.config['layers'][layer_index]
        x = np.asarray(x)
        if x.shape != (99, 64):
            raise ValueError('FFN input must be 99x64 (the corresponding norm1 output).')
        if encoded and x.dtype != np.dtype('<i2'):
            raise TypeError('Encoded FFN input must contain signed int16 codes.')
        codes = x if encoded else encode(x, layer['norm1_f'], self.stats, f'layer_{layer_index:02d}_ffn_input')
        return self._dense(codes, layer, 'ffn.fc1', f'layer_{layer_index:02d}_ffn_fc1')

    def encoder(self, x, encoded=False, trace=False):
        """Optional complete twelve-layer encoder; no preprocessing or classifier inside."""
        x = np.asarray(x)
        if x.shape != (99, 64):
            raise ValueError('Encoder input must be 99x64.')
        if encoded and x.dtype != np.dtype('<i2'):
            raise TypeError('Encoded encoder input must be signed int16.')
        x = x if encoded else encode(x, self.config['encoder_input_f'], self.stats, 'encoder_input')
        saved = {'encoder_input': x.copy()} if trace else {}
        for layer in self.config['layers']:
            prefix = f'layer_{layer["index"]:02d}_'
            q, k, v = [self._dense(x, layer, 'attention.' + kind, prefix + kind) for kind in ('q', 'k', 'v')]
            scores = exact_dot(q, k.T, self.backend)
            probabilities = softmax(scores, layer['q_f'] + layer['k_f'] + 3, self.parameters['lut.exp'])
            weighted = exact_dot(probabilities, v, self.backend)
            context = saturate16(round_shift(weighted, 15 + layer['v_f'] - layer['attention_weighted_values_f']),
                                 self.stats, prefix + 'attention_weighted_values')
            attention = self._dense(context, layer, 'attention.output', prefix + 'attention_output')
            residual1 = residual(x, layer['input_f'], attention, layer['attention_output_f'],
                                 layer['residual1_f'], self.stats, prefix + 'residual1')
            n1 = layer['norm']['norm1']
            norm1 = layer_norm(residual1, layer['residual1_f'], self.parameters[n1['gamma']], n1['gamma_f'],
                               self.parameters[n1['beta']], n1['beta_f'], layer['norm1_f'], self.stats, prefix + 'norm1')
            fc1 = self._dense(norm1, layer, 'ffn.fc1', prefix + 'ffn_fc1')
            activated = gelu(fc1, layer['ffn_fc1_f'], layer['gelu_f'], self.parameters['lut.gelu'], self.stats, prefix + 'gelu')
            fc2 = self._dense(activated, layer, 'ffn.fc2', prefix + 'ffn_fc2')
            residual2 = residual(norm1, layer['norm1_f'], fc2, layer['ffn_fc2_f'], layer['residual2_f'], self.stats, prefix + 'residual2')
            n2 = layer['norm']['norm2']
            y = layer_norm(residual2, layer['residual2_f'], self.parameters[n2['gamma']], n2['gamma_f'],
                           self.parameters[n2['beta']], n2['beta_f'], layer['output_f'], self.stats, prefix + 'output')
            if trace:
                values = {'input': x, 'q': q, 'k': k, 'v': v, 'qk_accumulator': scores,
                          'attention_probabilities': probabilities, 'attention_weighted_values': context,
                          'attention_output': attention, 'residual1': residual1, 'norm1': norm1,
                          'ffn_fc1': fc1, 'gelu': activated, 'ffn_fc2': fc2, 'residual2': residual2, 'output': y}
                saved.update({prefix + name: value.copy() for name, value in values.items()})
            x = y
        return (x, saved) if trace else x

    def decode_encoder(self, codes):
        return decode(codes, self.config['encoder_output_f']).astype('<f4')

    def decode_ffn(self, codes, layer_index):
        return decode(codes, self.config['layers'][layer_index]['ffn_fc1_f']).astype('<f4')
