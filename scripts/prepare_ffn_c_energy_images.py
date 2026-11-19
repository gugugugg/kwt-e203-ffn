"""Read the accepted IR payload bytes without changing their layout."""
from ffn_c_energy import BUILD


def prepare(name):
    return BUILD/'frozen/images'
