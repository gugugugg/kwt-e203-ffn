"""Causal private-macro replay of the already observed native case1 schedule.

Only accepted writes and synchronous read returns expose vector data. Other
layers reuse this control schedule as a model, not new CPU observations.
"""
import csv
import json
import sys
from pathlib import Path
from prepare import ROOT,OUT,REPORT
sys.path.insert(0,str(ROOT/'scripts/taskflow_study'))
from model import signed,rne

NATIVE=ROOT/'reports/optimization/ffn_taskflow_study/native-evidence/reports/optimization/ffn_taskflow_study/native-events.csv'
KEYS='cycle state row tile inner lane chunk emit_row soft_reset core_load load_kind load_address core_load_data core_load_pair quant mac_mask seed_mask in0_read in0_write in0_address in1_read in1_write in1_address'.split()

def hx(v,bits):
    return 'x'*((bits+3)//4) if v is None else format(v&((1<<bits)-1),'0%dx'%((bits+3)//4))

def packed(words):
    return ''.join(hx(x,16) for x in reversed(words))

def memory_hex(name):
    return [int(x,16) for x in (ROOT/'build/optimization/rtl/ffn_lp_IR/native_vectors'/name).read_text().split()]

def controls(row):
    return '%x %x %04x %04x %x'%(int(not row['soft_reset']),row['tile']&1,row['seed_mask'],row['mac_mask'],row['emit_row']*8+row['lane'])

def emit(stream,cycle,phase,row,iq,wq,bq,sq,check=0,expected=0):
    bias=[]
    for i in [0,2]:
        bias.append(None if bq[i] is None or bq[i+1] is None else signed(bq[i]|bq[i+1]<<16,32)&((1<<64)-1))
    stream.write('%d %d %s %x %s %s %s %s %x %08x\n'%(cycle,phase,controls(row),row['in0_read']|row['in1_read']<<1,
        packed(iq),packed(wq),hx(bias[1],64)+hx(bias[0],64),hx(sq,16),check,expected))

def generate(layer,rows):
    x=memory_hex('linear_%02d_input.hex'%layer)
    p=memory_hex('layer_%02d_parameters.hex'%layer)
    shifts=memory_hex('layer_%02d_shifts.hex'%layer)
    expected=memory_hex('linear_%02d_expected.hex'%layer)
    im=[{},{}];wm=[{} for _ in range(16)];bm=[{} for _ in range(4)];sm={}
    iq=[None,None];wq=[None]*16;bq=[None]*4;sq=None
    hold=[None,None];acc=[0]*16;sh=[0]*16;products=[0]*16;seeds=[0]*16
    outputs=macs=loads=0
    path=OUT/'stimuli'/('case%02d.txt'%layer)
    with path.open('w') as stream:
        for ix,row in enumerate(rows):
            cyc=row['cycle'];state=row['state'];tile=row['tile'];k=row['inner'];r=row['row']
            check=int(row['quant']);value=0
            if check:
                for offset in [0,1]:
                    lane=row['emit_row']*8+row['lane']+offset
                    index=(r+row['emit_row'])*256+tile*8+row['lane']+offset
                    assert products[lane]==64 and seeds[lane]==1,(layer,cyc,lane,products[lane],seeds[lane])
                    result=rne(acc[lane],sh[lane])&65535
                    assert result==expected[index],(layer,cyc,index,result,expected[index])
                    value|=result<<(16*offset);outputs+=1;products[lane]=seeds[lane]=0
            emit(stream,cyc,0,row,iq,wq,bq,sq,check,value)
            if row['soft_reset']:
                acc=[0]*16;sh=[0]*16;products=[0]*16;seeds=[0]*16
            else:
                for n in range(16):
                    if row['seed_mask']>>n&1:
                        q=(n%2)*2
                        assert bq[q] is not None and bq[q+1] is not None and sq is not None
                        acc[n]=signed(bq[q]|bq[q+1]<<16,32);sh[n]=signed(sq>>((n%2)*8),8);seeds[n]+=1
                    elif row['mac_mask']>>n&1:
                        a=hold[n//8];w=wq[(tile&1)*8+n%8]
                        assert a is not None and w is not None
                        acc[n]=signed(acc[n]+signed(a,16)*signed(w,16),36)
                        products[n]+=1;macs+=1
            # Accept data only when the old actual trace accepts the write.
            if row['core_load']:
                kind,addr=row['load_kind'],row['load_address'];count=2 if row['core_load_pair'] else 1
                if layer==0:
                    source=x if kind==0 else p if kind==1 else shifts
                    assert source[addr]==row['core_load_data'],(cyc,kind,addr)
                for i in range(count):
                    address=addr+i
                    if kind==0:
                        im[(address>>6)&1][((address>>7)&1)*64+(address&63)]=x[address]
                    elif kind==1:
                        if address<16384:
                            source_address=address//16
                            physical=((source_address&63)^((source_address&63)>>1))*16+(source_address>>6)
                            wm[address%16][physical]=p[address]
                        elif (address-16384)%4<2:
                            address-=16384;physical=(address//4)*2+address%4
                            bm[physical%4][physical//4]=p[addr+i]
                    elif kind==5:sm[address]=shifts[address]
                    loads+=1
            # Synchronous macro returns update after the accepting rising edge.
            for ir in range(2):
                if row['in%d_read'%ir] and not row['in%d_write'%ir]:
                    iq[ir]=im[ir][row['in%d_address'%ir]]
            if (state==6 and row['in0_read']) or (state==7 and k<63):
                request=k+int(state==7)
                physical=(request^(request>>1))*16+(tile>>1)
                for bank in range((tile&1)*8,(tile&1)*8+8):wq[bank]=wm[bank][physical]
            has_next=r<98 or tile<31
            first=state==7 and k==63 and has_next
            following=check and has_next and (row['emit_row'] or r==98) and row['lane']<6
            request=state==4 or first or following
            if request:
                target=tile if state==4 else (tile+1)%32
                pair=row['chunk'] if state==4 else 0 if first else row['lane']//2+1
                address=target*4+pair
                bq=[bm[bank][address] for bank in range(4)];next_sq=sm[address]
            else:next_sq=sq
            # Transparent HIGH input hold, LOW shift hold, including reset TE.
            for ir in range(2):
                if row['in%d_read'%ir] or row['soft_reset']:hold[ir]=iq[ir]
            high=rows[ix+1] if ix+1<len(rows) else row
            emit(stream,cyc,1,high,iq,wq,bq,sq)
            sq=next_sq
    assert outputs==25344 and macs==1622016
    return dict(layer=layer,cycles=len(rows),outputs=outputs,logical_products=macs,accepted_load_words=loads,
        passed=True,stimulus=str(path.relative_to(ROOT)),schedule='existing native case1' if layer==0 else 'case1 schedule model with layer-specific causally loaded data',
        macro_read_before_load=False,unknown_startup_macro_Q_preserved=True)

def main():
    (OUT/'stimuli').mkdir(exist_ok=True)
    rows=[]
    with NATIVE.open() as stream:
        for raw in csv.DictReader(stream):rows.append({k:int(raw[k],16) for k in KEYS})
    assert len(rows)==148271
    result=dict(cases=[])
    for layer in range(12):
        result['cases'].append(generate(layer,rows))
        (REPORT/'stimuli.json').write_text(json.dumps(result,indent=2))
        print('SLICE_CAUSAL_STIMULUS_PASS',layer,flush=True)
    result['passed']=True
    (REPORT/'stimuli.json').write_text(json.dumps(result,indent=2))

if __name__=='__main__':main()
