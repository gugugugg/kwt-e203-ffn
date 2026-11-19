"""Read the accepted IR payload bytes without changing their layout."""
from ffn_sr_area import BUILD


def prepare(name):
    return BUILD/'frozen/images'
