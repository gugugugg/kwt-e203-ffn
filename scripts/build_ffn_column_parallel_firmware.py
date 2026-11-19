"""Reuse the frozen IR firmware bytes; no recompilation or new payload."""
from ffn_column_parallel import ROOT, load, copy_tree, dump, REPORT


def build(name):
    source = ROOT/load(name)['parent']['firmware']
    target = ROOT/'build/optimization/firmware'/name
    copy_tree(source, target)
    compared=[]
    for path in source.rglob('*'):
        if path.is_file():
            other=target/path.relative_to(source)
            if other.read_bytes()!=path.read_bytes(): raise RuntimeError('Firmware copy differs')
            compared.append(path.relative_to(source).as_posix())
    dump(REPORT/'firmware-reuse.json', dict(source=str(source.relative_to(ROOT)),
        target=str(target.relative_to(ROOT)), byte_equal=True, files=compared, recompiled=False))
    return target
