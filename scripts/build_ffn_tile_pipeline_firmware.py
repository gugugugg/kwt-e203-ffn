"""All fifth-round hardware candidates use the exact accepted driver binary."""
from ffn_tile_pipeline import ROOT, load, copy_tree


def build(name):
    parent = load(name)['parent']
    destination = ROOT / 'build/optimization/firmware' / name
    copy_tree(ROOT / parent['firmware'], destination)
    return destination


if __name__ == '__main__':
    import sys
    for name in sys.argv[1:]:
        print(build(name))
