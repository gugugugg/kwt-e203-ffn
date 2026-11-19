"""Reuse the accepted fifth-round payload bytes without reordering them."""
from ffn_area_power import BUILD, freeze


def prepare(name):
    freeze()
    return BUILD / 'frozen/images'


if __name__ == '__main__':
    import sys
    for name in sys.argv[1:]:
        print(prepare(name))
