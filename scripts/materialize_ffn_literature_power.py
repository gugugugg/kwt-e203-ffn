"""Generate only round-nine candidates from their frozen accepted IR source."""
import json
from ffn_literature_power import ROOT,load,candidates,copy_tree
from literature_power_compute import transform
from materialize_ffn_loading_dma import add_ports,wires,connections,CHANNELS

def prepare(name):
    manifest=load(name)
    out=ROOT/'build/optimization/rtl_sources'/name
    copy_tree(ROOT/manifest['parent']['source_snapshot'],out)
    path=out/'encoder/kwt_encoder.sv'
    path.write_bytes(transform(path.read_text(),manifest['literature_power_hardware']).encode('utf-8'))
    (out/'literature-power-configuration.json').write_text(json.dumps(manifest,indent=2))
    return out

def variants():return {name:['PIPE','OUTPUT'] for name in candidates()}
