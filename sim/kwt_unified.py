import json
from pathlib import Path

import numpy as np

from sim.fixed_ops import encode,exact_dot,round_shift,saturate16
from sim.kwt_fixed import FixedKWT


class UnifiedKWT:
    def __init__(self,directory,backend='int64'):
        self.directory=Path(directory)
        self.config=json.loads((self.directory/'manifest.json').read_text())
        self.encoder_model=FixedKWT(self.directory/self.config['encoder_package'],backend=backend)
        self.backend=backend
        self.stats={}
        self.linear_parameters=[]
        for layer in self.config['linear_layers']:
            raw=(self.directory/layer['parameters']).read_bytes()
            self.linear_parameters.append({
                'kernel':np.frombuffer(raw,dtype='<i2',count=16384).reshape(64,256),
                'bias':np.frombuffer(raw,dtype='<i8',count=256,offset=32768),
                'shifts':np.fromfile(self.directory/layer['shifts'],dtype='i1')})

    def linear(self,x,layer,encoded=False):
        cfg=self.config['linear_layers'][layer]
        p=self.linear_parameters[layer]
        codes=x if encoded else encode(x,np.asarray(cfg['input_f']),self.stats,'linear_%02d_input'%layer)
        acc=exact_dot(codes,p['kernel'],self.backend)+p['bias']
        result=np.empty_like(acc)
        for shift in np.unique(p['shifts']):
            selected=p['shifts']==shift
            result[:,selected]=round_shift(acc[:,selected],int(shift))
        return saturate16(result,self.stats,'linear_%02d_output'%layer)

    def decode_linear(self,codes,layer):
        return codes.astype(np.float64)*np.exp2(-np.asarray(self.config['linear_layers'][layer]['output_f']))

    def encoder(self,x,encoded=False,trace=False):
        return self.encoder_model.encoder(x,encoded=encoded,trace=trace)
