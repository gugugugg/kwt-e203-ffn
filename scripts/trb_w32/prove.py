"""Prove the W32 integer identity and the bit widths used by the RTL."""
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_trb_w32'


def signed(value, width):
    return (value + (1 << (width-1))) % (1 << width) - (1 << (width-1))


def main():
    # Multiplication expands over Z and its image in Z/(2**36).
    lhs = {('a0','w0'): 1, ('a1','w1'): 1}
    rhs = {}
    for a,b in itertools.product(('a0','w1'),('a1','w0')):
        term=tuple(sorted((a,b)))
        rhs[term]=rhs.get(term,0)+1
    for term in (('a0','a1'),('w0','w1')):
        rhs[term]-=1
    assert lhs=={term:coefficient for term,coefficient in rhs.items() if coefficient}
    bounds=(-32768,32767)
    sums=(2*bounds[0],2*bounds[1])
    products=[a*b for a,b in itertools.product(sums,repeat=2)]
    assert all(signed(x,17)==x for x in sums)
    assert all(signed(x,34)==x for x in (min(products),max(products)))
    for a,b,c in itertools.product((0,1),repeat=3):
        assert a+b+c == (a^b^c)+2*((a&b)|(a&c)|(b&c))
    for shift in range(256):
        code=shift-12 if 13<=shift<=18 else 0
        assert (code+12 if code else 0)==(shift if 13<=shift<=18 else 0)
    values=(-32768,-32767,-1,0,1,32766,32767)
    for a0,a1,w0,w1 in itertools.product(values,repeat=4):
        p=signed((a0+w1)*(a1+w0),34)
        left=a0*w0+a1*w1
        for bias in (-(1<<35),-1,0,(1<<35)-1):
            assert signed(left+bias,36)==signed(p-a0*a1-w0*w1+bias,36)
    result=dict(passed=True,method='symbolic coefficient identity over integers and modular reduction',
                signed16_range=bounds,preadd_range=sums,product_range=[min(products),max(products)],
                feedback_width=36,carry_save_truth_table_rows=8,all_shift_bytes_checked=256,
                directed_signed_edges=len(values)**4*4)
    (REPORT/'arithmetic-proof.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result)


if __name__=='__main__':
    main()
