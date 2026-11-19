"""Resolve this checkpoint's remaining physical state encodings."""
import json
import re
from phase import REVIEW


def read(name):
    return json.loads((REVIEW/name).read_text())


def write(name, data):
    (REVIEW/name).write_text(json.dumps(data,indent=2)+'\n')


def resolve():
    inv, conn = read('inventory.json'), read('connectivity.json')
    cells, reps = inv['cells'], conn['representatives']
    pending = read('phase-review-pending.json')
    draft = read('corrections-draft.json')
    reviewed = read('physical-cell-phase-review.json')
    native = read('phase-extra-segments/result.json')
    assert native['passed'] and native['tag']==inv['tag']
    models = {m[1]:m[2].split('specify')[0] for m in re.finditer(
        r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule',(REVIEW/'vendor-functions.v').read_text())}
    indexed = {row['rtl']:row for row in read('cell-inverted-review-inputs.json')}

    def rep(net):
        return reps.get(net,net)

    def driver(net):
        row, = conn['drivers'][rep(net)]
        return dict(row,pins={pin:value.strip() for pin,value in cells[row['cell']]['pins'].items()})

    def literal(ref, primitive, arguments):
        assert re.search(r'\b'+primitive+r'\s+(?:\w+\s*)?\(\s*'+
                         r'\s*,\s*'.join(map(re.escape,arguments.split(',')))+r'\s*\)',models[ref]), ref

    def inverter(step, signal=None):
        literal(step['ref'],'not','ZN,I')
        if signal is not None:
            assert step['pins']['I']==signal

    for item in pending:
        assert item['kind']=='cell_encoding'
        rtl=item['rtl']
        row=indexed[rtl]
        path,ref=row['gate'],row['ref']
        parent=path.rsplit('/',1)[0]+'/'
        pins={k:v.strip() for k,v in row['pins'].items()}
        short=rtl.rsplit('/',1)[-1]
        assert 'QN' in pins
        literal(ref,'not','QN,n0')
        evidence=dict(cell=path,ref=ref,pins=pins)
        if ref=='EDQNV6_12TR40' and short.startswith('qout_r['):
            capture=driver(parent+pins['D'])
            inverter(capture,short.replace('qout_r','dnxt'))
            assert pins['E']=='lden' and pins['QN']==short.replace('qout_r','qout')
            literal(ref,'udp_edff','n0,D,CK,xRN,xSN,E,NOTIFIER')
            evidence['capture_inverse']=capture
            reason='The enabled D pin receives inverted dnxt, and the literal QN restores the original FIFO state.'
        elif ref=='DSNQNV6_12TR40' and short=='state[0]':
            # CLEAR is zero in the frozen RTL. The cell asynchronously sets its
            # internal state to one, exposing zero on QN to the FSM consumers.
            assert pins['QN']==short
            literal(ref,'buf','xSN,SDN')
            literal(ref,'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
            set_drive=driver(parent+pins['SDN'])
            inverter(set_drive)
            next_drive=driver(parent+pins['D'])
            literal(next_drive['ref'],'or','outA,A1,A2')
            feedback=driver(parent+next_drive['pins']['A2'])
            inverter(feedback,short)
            evidence.update(set_drive=set_drive,next_state=next_drive,feedback=feedback)
            reason='Active-low SDN sets the internal DFF on reset, making physical QN zero for CLEAR. The routed QN feeds the original state bit, and the D cone uses the complementary feedback encoding.'
        elif ref=='EDGRNQNV6_12TR40' and short=='jp_input_return[72]':
            assert pins['D']=="1'b1" and pins['QN']==short
            literal(ref,'udp_edfft','n0,D,CK,xRN,xSN,E,NOTIFIER')
            select=driver(parent+pins['RN'])
            literal(select['ref'],'and','outA,A2,A1')
            literal(select['ref'],'and','outB,B2,B1')
            literal(select['ref'],'nor','ZN,outA,outB')
            mux=select['pins']
            assert mux['A1']=='ap_input_rows_2__generation_data[8]' and mux['B2']=='ap_input_rows_2__generation_data[24]'
            first=driver(parent+mux['A2']); inverter(first)
            gen0=driver(parent+first['pins']['I'])
            literal(gen0['ref'],'or','Z,A1,A2')
            gen1=driver(parent+mux['B1'])
            literal(gen1['ref'],'nor','ZN,A1,A2')
            assert rep(parent+gen0['pins']['A1'])==rep(parent+gen1['pins']['A1'])
            assert gen0['pins']['A2']=='input_read_generation'
            gen1_inv=driver(parent+gen1['pins']['A2']); inverter(gen1_inv)
            gen1_delay=driver(parent+gen1_inv['pins']['I'])
            literal(gen1_delay['ref'],'buf','Z,I')
            assert rep(parent+gen1_delay['pins']['I'])==rep(parent+'input_read_generation')
            enable_buf=driver(parent+pins['E']);literal(enable_buf['ref'],'buf','Z,I')
            enable_inv=driver(parent+enable_buf['pins']['I']); inverter(enable_inv)
            assert rep(parent+enable_inv['pins']['I'])==rep(parent+gen0['pins']['A1'])
            gate=parent+'ap_input_rows_2__return_copies_0__return_gate/cell_gate'
            assert rep(conn['pins'][path+'/CK'])==rep(conn['pins'][gate+'/Q'])
            gate_e=driver(conn['pins'][gate+'/E']); inverter(gate_e)
            assert rep(gate_e['cell'].rsplit('/',1)[0]+'/'+gate_e['pins']['I'])==rep(parent+gen0['pins']['A1'])
            evidence.update(selected_reset=select,generation0=[first,gen0],generation1=[gen1,gen1_inv,gen1_delay],
                            enable=[enable_buf,enable_inv,gate_e],gate=cells[gate])
            reason='At capture, the two bank enables select exactly the actual generation. RN is the complement of that bit and D is one. The synchronous reset captures zero when RN is low, so QN restores the selected positive input bit.'
        else:
            raise RuntimeError('Unresolved actual state encoding: '+rtl)
        reviewed.append(dict(rtl=rtl,physical_inverted=False,output='QN',
                             net=row['QN_net'],reason=reason,evidence=evidence))

    # The candidate's DMA ACK signals remain real routed ports in the mapped SoC.
    engine, = [name for name in cells if name.endswith('/dma_frontend/loading_dma')]
    arbiter='shared_memory/memory_arbiter'
    ports={}
    for field in ('valid','ready'):
        signal='ld_rsp_'+field
        for scope in ('shared_memory','soc'):
            assert cells[scope]['pins'][signal].strip()==signal
        assert cells[arbiter]['pins']['b_rsp_'+field].strip()==signal
        assert rep(engine.rsplit('/',1)[0]+'/'+cells[engine]['pins']['mem_rsp_'+field].strip())==rep(signal)
        ports[field]=driver(signal)
    literal(ports['ready']['ref'],'buf','Q,n0')
    literal(ports['valid']['ref'],'and','Z,A1,A2')
    assert ports['ready']['cell']==engine+'/pd_active_reg'
    assert ports['valid']['pins']['A1']=='s_rsp_valid'
    write('mapped-ack-interface.json',dict(passed=True,tag=inv['tag'],variant=inv['variant'],
        valid_expression='dut.ld_rsp_valid',ready_expression='dut.ld_rsp_ready',connections=ports))

    prefix={path:cell for path,cell in cells.items() if path.startswith(
        ('shared_memory/input_committed_reg_','shared_memory/input_background_phase_reg'))}
    assert len(prefix)==13
    for cell in prefix.values():
        assert 'Q' in cell['pins'] and 'QN' not in cell['pins']
        literal(cell['ref'],'buf','Q,n0')
    write('staged-state-physical-review.json',dict(tag=inv['tag'],positive_Q_registers=prefix))
    write('resolved-staged-phase-inputs.json',pending)
    draft['pending']=0
    write('corrections-draft.json',draft)
    write('physical-cell-phase-review.json',reviewed)
    print('Q16_STAGED_PHASE_RESOLVED',len(pending),len(draft['aliases']),flush=True)


if __name__=='__main__':
    resolve()
