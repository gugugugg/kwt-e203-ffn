"""Materialize the only fixed32MAC candidate."""
from c16_efficiency.prepare import prepare as materialize
from materialize_ffn_loading_dma import add_ports, wires, connections, CHANNELS


def prepare(name):
    if name != 'ffn_ce_W': raise ValueError(name)
    return materialize()[1]


def variants():
    return {'ffn_ce_W':['PIPE','OUTPUT']}
