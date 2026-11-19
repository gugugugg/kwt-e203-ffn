import json
from pathlib import Path

import numpy as np

from sim.fixed_ops import encode, exact_dot, round_shift, saturate16


class ChannelFFN:
    def __init__(self, directory, backend='exact-f64'):
        self.directory = Path(directory)
        self.config = json.loads((self.directory / 'manifest.json').read_text())
        self.parameters = [dict(np.load(self.directory / ('layer_%02d.npz' % i))) for i in range(12)]
        self.backend = backend
        self.stats = {}

    def ffn(self, x, layer, encoded=False):
        cfg = self.config['layers'][layer]
        p = self.parameters[layer]
        codes = x if encoded else encode(x, np.asarray(cfg['input_f']), self.stats, 'layer_%02d_input' % layer)
        acc = exact_dot(codes, p['kernel'], self.backend) + p['bias']
        quantized = np.empty_like(acc)
        for shift in np.unique(p['shifts']):
            selected = p['shifts'] == shift
            quantized[:, selected] = round_shift(acc[:, selected], int(shift))
        return saturate16(quantized, self.stats, 'layer_%02d_output' % layer)

    def decode_ffn(self, codes, layer):
        return codes.astype(np.float64) * np.exp2(-np.asarray(self.config['layers'][layer]['output_f']))
