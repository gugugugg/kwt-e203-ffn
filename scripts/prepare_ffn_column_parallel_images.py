"""Read the accepted IR payload bytes without changing their layout."""
from ffn_column_parallel import BUILD


def prepare(name):
    return BUILD/'frozen/images'
