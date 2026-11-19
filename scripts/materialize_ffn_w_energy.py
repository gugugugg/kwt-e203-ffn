from w_energy.prepare import prepare as materialize,variants as selected_variants
from materialize_ffn_loading_dma import add_ports,wires,connections,CHANNELS
def prepare(name):return materialize(name)[1]
def variants():return {name:['PIPE','OUTPUT'] for name in selected_variants()}
