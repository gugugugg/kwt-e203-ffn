"""Resolve the final candidate's remaining activity and ACK polarity evidence."""
from pathlib import Path
import json
import re

from phase import REVIEW


def load(name):
    return json.loads((REVIEW/name).read_text())


def save(name, data):
    (REVIEW/name).write_text(json.dumps(data,indent=2)+'\n')


def resolve():
    inv=load('inventory.json')
    conn=load('connectivity.json')
    cells, reps=inv['cells'], conn['representatives']
    draft=load('corrections-draft.json')
    pending=load('phase-review-pending.json')
    reviewed=load('physical-cell-phase-review.json')
    rules={row['rtl']:row for row in load('cell-inverted-review-inputs.json')}

    def driver(net):
        row,=conn['drivers'][reps.get(net,net)]
        return dict(row, pins=cells[row['cell']]['pins'])

    def literal(cell, term):
        library=(REVIEW/'vendor-functions.v').read_text()
        block=re.search(r'\bmodule\s+'+cell+r'\s*\((.*?)endmodule',library,re.S)
        if not block or not re.search(term,block[1].split('specify')[0]):
            raise RuntimeError('Missing literal primitive: '+cell)

    def capture_chain(parent, net):
        stage=[]
        while net!='n16011':
            step=driver(parent+net)
            stage.append(step)
            assert re.fullmatch(r'(CLKINV|BUF)V?\w*',step['ref'])
            net=step['pins']['I'].strip()
        assert sum('INV' in s['ref'] for s in stage)%2==0
        return stage

    assert len(pending)==28
    for row in pending:
        assert row['kind']=='cell_encoding'
        rtl=row['rtl']
        short=rtl.rsplit('/',1)[1]
        cell=rules[rtl]
        ref,pins=cell['ref'],cell['pins']
        parent=row['cell'].rsplit('/',1)[0]+'/'
        cone={}
        inverted=False
        if ref.startswith('EDGRNQN'):
            literal(ref,r'udp_edfft.*?\(n0, D, CK, xRN, xSN, E, NOTIFIER\)')
            literal(ref,r'not\s+I2\s*\(QN, n0\)')
            assert pins['D']=="1'b1"
            cone['reset']=driver(parent+pins['RN'])
            assert cone['reset']['ref']=='NAND2CV0_12TR40'
            expected={'operand_weight[144]':'pm_rdata[144]', 'operand_weight[112]':'pm_rdata[112]',
                      'jp_input_return[34]':'ap_input_rdata[18]'}
            assert cone['reset']['pins']['A1']==expected[short]
            cone['reset_capture']=capture_chain(parent,cone['reset']['pins']['A2'])
            cone['enable_capture']=capture_chain(parent,pins['E'])
            why='Capture-qualified synchronous RN is NAND of positive operand and enable. The internal state records its inverse; QN restores the operand.'
        elif ref=='DQNV6_12TR40':
            literal(ref,r'not\s+I2\s*\(QN, n0\)')
            gate=driver(parent+pins['D'])
            assert gate['ref']=={'jp_input_return[17]':'OA21V0_12TR40',
                                 'jp_input_return[93]':'OAI21V0_12TR40'}[short]
            cone['D']=gate
            cone['load']=driver(parent+gate['pins']['B'])
            assert cone['load']['ref']=='NAND2CV0_12TR40'
            assert cone['load']['pins']['A1']=={'jp_input_return[17]':'ap_input_rdata[1]',
                                                'jp_input_return[93]':'ap_input_rdata[45]'}[short]
            cone['capture_select']=capture_chain(parent,gate['pins']['A1'])
            cone['capture_operand']=capture_chain(parent,cone['load']['pins']['A2'])
            inverted=short=='jp_input_return[93]'
            why='On the capture edge the OR term is high. NAND of operand and capture feeds the final AND or NAND, then the literal flop QN inverts D.'
        elif ref=='EDQNV6_12TR40':
            literal(ref,r'not\s+I1\s*\(QN, n0\)')
            assert '/u_sirv_gnrl_cmd_fifo/' in rtl and pins['E']=='lden'
            cone['D']=driver(parent+pins['D'])
            assert cone['D']['ref']=='CLKINV0_12TR40'
            assert cone['D']['pins']['I']==short.replace('qout_r','dnxt')
            assert pins['QN']==short.replace('qout_r','qout')
            why='With the FIFO enable asserted an actual inverter drives D from dnxt; the vendor QN inverter restores the positive FIFO state.'
        elif ref=='DQV0_12TR40':
            literal(ref,r'udp_dff')
            assert short=='qout_r[58]' and pins['Q']=='n162'
            cone['D']=driver(parent+pins['D'])
            assert cone['D']['pins']==dict(I0='n162',I1='n96',S='lden',Z='n163')
            subtree=[c for p,c in cells.items() if p.startswith(parent) and '/' not in p[len(parent):]]
            assert any(c['ref']=='CLKINV0_12TR40' and c['pins']==dict(I='dnxt[58]',ZN='n96') for c in subtree)
            assert any(c['ref']=='INV32_12TR40' and c['pins']==dict(I='n162',ZN='qout[58]') for c in subtree)
            inverted=True
            why='The enable mux stores inverted dnxt and holds inverted Q. The consumer inverter restores qout[58]; the cell Q itself is negative.'
        elif ref=='DRSNQNV2_12TR40':
            literal(ref,r'not\s+I2\s*\(QN, n0\)')
            assert short=='qout_r[0]' and pins['SDN']=='rst_n' and pins['RDN']=="1'b1"
            cone['D']=driver(parent+pins['D'])
            assert cone['D']['ref']=='MUX2NV0_12TR40'
            assert cone['D']['pins']==dict(I0='qout[0]',I1='dnxt[0]',S='lden',ZN='n1')
            literal(cone['D']['ref'],r'not\s+I01\s*\(ZN, z\)')
            why='The enabled D cone inverts either the next bit or held Q. Vendor QN restores positive data and the internal asynchronous set resets QN to zero.'
        else:
            raise RuntimeError('Unresolved phase: '+rtl)
        output='Q' if 'Q_net' in cell else 'QN'
        gate=cell[output+'_net']
        evidence=dict(cell=row['cell'],ref=ref,pins=pins,cone=cone)
        reviewed.append(dict(rtl=rtl,physical_inverted=inverted,output=output,
                             net=gate,reason=why,evidence=evidence))
        if inverted:
            draft['replace_native_cell_aliases'].append(rtl)
            draft['aliases'].append(dict(rtl=rtl,gate=gate,inverted=True,reason=why,evidence=evidence))
    draft['pending']=0
    save('resolved-stream-cell-inputs.json',pending)
    save('corrections-draft.json',draft)
    save('physical-cell-phase-review.json',reviewed)

    engine,=[p for p in cells if p.endswith('/dma_frontend/loading_dma')]
    dma_parent=engine.rsplit('/',1)[0]+'/'
    arbiter='shared_memory/memory_arbiter'
    interfaces={}
    for field in ('valid','ready'):
        top='ld_rsp_'+field
        suffix='_BAR' if field=='ready' else ''
        shared=top+suffix
        ep='mem_rsp_'+field+suffix
        bp='b_rsp_'+field+suffix
        assert cells['shared_memory']['pins'][shared].strip()==cells['soc']['pins'][shared].strip()==top
        assert cells[arbiter]['pins'][bp].strip()==shared
        dma=dma_parent+cells[engine]['pins'][ep].strip()
        assert reps.get(dma,dma)==reps.get(top,top)
        interfaces[field]=dict(signal=top,engine_pin=engine+'/'+ep,arbiter_pin=arbiter+'/'+bp)
    ready=driver('ld_rsp_ready')
    assert ready['cell'].startswith(engine+'/') and ready['ref']=='INV0_12TR40'
    assert ready['pins']==dict(I='busy',ZN='busy_BAR')
    literal(ready['ref'],r'not\s+\w+\s*\(ZN, I\)')
    interfaces['ready']['physical_inverted']=True
    interfaces['ready']['driver']=ready
    save('mapped-ack-interface.json',dict(passed=True,tag=inv['tag'],variant=inv['variant'],
         valid_expression='dut.ld_rsp_valid',ready_expression='(!dut.ld_rsp_ready)',connections=interfaces))
    print('R3O_STREAM_PHASE_RESOLVED',len(pending),len(draft['aliases']),flush=True)


if __name__=='__main__':
    resolve()
