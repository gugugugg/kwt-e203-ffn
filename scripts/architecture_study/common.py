"""Frozen inputs and exact arithmetic for the three-route architecture study."""
from pathlib import Path
import json
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/'reports/optimization/ffn_architecture_study'
REPORT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'scripts/taskflow_study'))
from model import Core,OutputQueue,signed,rne

MASK36=(1<<36)-1


def dump(name,value):
    path=REPORT/name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')


def arrays(layer):
    base=ROOT/'build/optimization/ffn_transport/testdata'
    p=base/('layer_%02d_parameters.bin'%layer)
    x=np.fromfile(base/('linear_%02d_input.bin'%layer),dtype='<i2').astype(np.int64).reshape(99,64)
    w=np.frombuffer(p.read_bytes()[:32768],dtype='<i2').astype(np.int64).reshape(64,256)
    b=np.frombuffer(p.read_bytes()[32768:],dtype='<i8').copy()
    sh=np.fromfile(base/('layer_%02d_shifts.bin'%layer),dtype='i1').astype(np.int64)
    expected=np.fromfile(base/('linear_%02d_expected.bin'%layer),dtype='<i2').astype(np.int64).reshape(99,256)
    return x,w,b,sh,expected


def wrap36(x):
    return ((x+(1<<35))&MASK36)-(1<<35)


def quantize(acc,shifts):
    out=np.empty_like(acc)
    for col,shift in enumerate(shifts):
        if shift not in range(13,19):
            out[:,col]=0
            continue
        q=acc[:,col]>>shift
        rem=acc[:,col]&((1<<shift)-1)
        out[:,col]=np.clip(q+((rem>(1<<(shift-1)))|((rem==(1<<(shift-1)))&((q&1)!=0))),-32768,32767)
    return out


def coefficient_table(a):
    """Combinational multiples 0..15: four shifts, eleven explicit additions."""
    t=np.zeros((len(a),16),dtype=np.int64)
    for k in [1,2,4,8]:t[:,k]=a*k
    for k,left,right in [(3,2,1),(5,4,1),(6,4,2),(7,6,1),(9,8,1),(10,8,2),
                         (11,10,1),(12,8,4),(13,12,1),(14,12,2),(15,14,1)]:
        t[:,k]=t[:,left]+t[:,right]
    return t


def nibble_products(a,w):
    t=coefficient_table(a)
    word=w&65535
    result=np.zeros((len(a),len(w)),dtype=np.int64)
    for digit in range(4):
        d=(word>>(digit*4))&15
        if digit==3:
            d=np.where(d>=8,d-16,d)
            result+=np.where(d[None,:]<0,-t[:,np.abs(d)],t[:,np.abs(d)])<<(digit*4)
        else:result+=t[:,d]<<(digit*4)
    return result


def bit_products(a,w):
    magnitude=np.abs(w.astype(np.int64))
    result=np.zeros((len(a),len(w)),dtype=np.int64)
    for bit in range(16):
        result+=((magnitude>>bit)&1)[None,:]*(a[:,None]<<bit)
    return np.where(w[None,:]<0,-result,result)


def freeze():
    frozen=REPORT/'frozen'
    frozen.mkdir(exist_ok=True)
    for relative in ['constraints/ffn_selected.json','constraints/ffn_next_objective.json',
                     'reports/optimization/ffn_taskflow_study/native-model-summary.json',
                     'reports/optimization/ffn_taskflow_study/cost-budget.json']:
        src=ROOT/relative
        target=frozen/src.name
        if target.exists() and target.read_bytes()!=src.read_bytes():
            raise RuntimeError('Study frozen reference changed: '+relative)
        target.write_bytes(src.read_bytes())
    assert (ROOT/'constraints/ffn_selected.json').read_bytes()==(ROOT/'reports/optimization/ffn_taskflow_study/frozen/ffn_selected.json').read_bytes()
    dump('protocol.json',dict(reference='ffn_lp_IR',precision='Q2/int16, signed36 modular accumulation, exact RNE/saturation',
         limits=dict(throughput_min=1000,area_max_mm2=.221187458,power_max_w=.022464915030806946),
         new_RTL=False,native_CPU=False,synthesis_STA_power=False,agents=False,
         fixed_models=dict(A='4x4, four double-buffered input banks, seven statically partitioned output banks, FIFO16 and held2',
                           B='4-bit exact coefficient sharing: 0..15 activation multiples from 11 adders per row, combinational selectors, signed top digit; no new table registers',
                           C='16 term-serial MAC lanes, weight magnitude bits with eight 16-bit masks; one preparation clock per inner plus max weight-bit count clocks; no lookahead or input-dependent offline schedule'),
         unchanged_host_payload=11936,guards=5,control=5,logical_products_per_output=64,
         predicted_PPA_not_accepted=True,recommendations_max=1))


if __name__=='__main__':freeze()
