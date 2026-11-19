"""Materialize the only fixed32MAC candidate."""
from column_parallel.prepare import prepare as materialize
from materialize_ffn_loading_dma import add_ports, wires, connections, CHANNELS


def prepare(name):
    if name != 'ffn_cp_C16': raise ValueError(name)
    return materialize()[1]


def variants():
    return {'ffn_cp_C16':['PIPE','OUTPUT']}
