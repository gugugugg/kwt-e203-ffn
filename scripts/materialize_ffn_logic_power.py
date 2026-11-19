"""Materialize the bounded round-eight matrix from the exact HM2 snapshot."""
import json
from ffn_logic_power import ROOT,load,candidates,copy_tree
from logic_power_compute import transform
from materialize_ffn_loading_dma import add_ports,wires,connections,CHANNELS

def prepare(name):
    manifest=load(name)
    out=ROOT/'build/optimization/rtl_sources'/name
    copy_tree(ROOT/manifest['parent']['source_snapshot'],out)
    path=out/'encoder/kwt_encoder.sv'
    path.write_bytes(transform(path.read_text(),manifest['logic_power_hardware']).encode('utf-8'))
    (out/'logic-power-configuration.json').write_bytes(json.dumps(manifest,indent=2).encode('utf-8'))
    return out

def variants():return {name:['PIPE','OUTPUT'] for name in candidates()}
