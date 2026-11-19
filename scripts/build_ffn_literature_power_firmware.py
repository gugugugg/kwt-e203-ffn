"""All four interfaces reuse the accepted HM2 firmware without recompiling."""
from ffn_literature_power import ROOT,load,copy_tree

def build(name):
    destination=ROOT/'build/optimization/firmware'/name
    copy_tree(ROOT/load(name)['parent']['firmware'],destination)
    return destination
