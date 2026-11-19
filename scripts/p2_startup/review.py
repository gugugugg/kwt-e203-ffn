"""Resolve the remaining phase cases of the actual S+G mapped design."""
import json
from pathlib import Path
import re

from native import NAME, ROOT, phases
from resolve_overlap_phase import resolve
from sr_area_phase_review import native_index


def run():
    _, _, _, review = phases.bind('P2', variant=NAME)

    def read(name):
        return json.loads((review / (name+'.json')).read_text())

    def write(name, data):
        (review / (name+'.json')).write_text(json.dumps(data, indent=2)+'\n')

    path = review/'phase-review-pending.json'
    original = path.read_bytes()
    pending = json.loads(original)
    fifo_cells = [row for row in pending if row['kind']=='cell_encoding' and '/qout_r[' in row['rtl']]
    # The established checks validate the literal FIFO capture, ACK route and
    # prefix register cells on this checkpoint before we examine its new cones.
    try:
        write('phase-review-pending', fifo_cells)
        resolve('P2', variant=NAME)
    finally:
        path.write_bytes(original)
    inventory, conn = read('inventory'), read('connectivity')
    models = {m[1]:m[2].split('specify')[0] for m in re.finditer(
        r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule', (review/'vendor-functions.v').read_text())}
    segments = native_index(review/'segments.rpt')
    segments.update(native_index(review/'additional-segments/segments.rpt'))
    segments.update(native_index(review/'phase-extra-segments/segments.rpt'))
    draft, checked = read('corrections-draft'), read('physical-cell-phase-review')
    cell_rows = {row['rtl']:row for row in read('cell-inverted-review-inputs')}
    cells = inventory['cells']
    representatives = conn['representatives']

    def rep(net):
        return representatives.get(net,net)

    def pin(cell, key):
        return rep(conn['pins'][cell+'/'+key])

    def literal(ref, primitive, signature):
        expression = r'\b'+primitive+r'\s+(?:\w+\s*)?\(\s*'+r'\s*,\s*'.join(
            map(re.escape,signature.split(',')))+r'\s*\)'
        assert re.search(expression,models[ref]), (ref, signature)

    def driver(net):
        row, = conn['drivers'][rep(net)]
        cell = cells[row['cell']]
        return dict(row, pins={k:v.strip() for k,v in cell['pins'].items()})

    def upstream(gate, key):
        return driver(pin(gate['cell'],key))

    def inverted(gate):
        literal(gate['ref'],'not','ZN,I')
        return gate['pins']['I']

    def record_alias(row, negative, why, evidence):
        draft['aliases'].append(dict(rtl=row['rtl'],gate=row['gate'],inverted=negative,
                                     reason=why,evidence=evidence))

    for row in pending:
        if row in fifo_cells:
            continue
        if row['kind']=='cell_encoding':
            rtl, cell, ref = row['rtl'], row['cell'], row['ref']
            bit = int(rtl.rsplit('[',1)[1][:-1])
            assert '/jp_input_return[' in rtl and bit//16%4==0 and ref=='EDQNV6_12TR40'
            literal(ref,'udp_edff','n0,D,CK,xRN,xSN,E,NOTIFIER')
            literal(ref,'not','QN,n0')
            boundary = cell_rows[rtl]
            target = boundary['QN_net']
            p = cells[cell]['pins']
            assert p['QN'].strip()=='jp_input_return[%d]'%bit
            base = 'ap_input_rows_%d__generation_data' % (bit//64)
            gen0, gen1 = ('%s[%d]'%(base,bit%16+16*g) for g in range(2))
            data = driver(pin(cell,'D'))
            if data['ref']=='MUX2NV0_12TR40':
                literal(data['ref'],'udp_mux2','z,I0,I1,S')
                literal(data['ref'],'not','ZN,z')
                assert (data['pins']['I0'],data['pins']['I1'])==(gen0,gen1)
                selector = upstream(data,'S')
                inverted(selector)
                negative_select = upstream(selector,'I')
                cone = [data,selector]
            else:
                assert bit==203
                inverted(data)
                mux = upstream(data,'I')
                literal(mux['ref'],'and','OUT0,A1,A2')
                literal(mux['ref'],'not','B_inv,B')
                literal(mux['ref'],'or','Z,OUT0,B_inv')
                other = upstream(mux,'B')
                literal(other['ref'],'nand','ZN,A1,A2')
                assert (mux['pins']['A1'],other['pins']['A1'])==(gen0,gen1)
                selector = upstream(other,'A2')
                assert inverted(selector)==mux['pins']['A2']
                negative_select = upstream(mux,'A2')
                cone = [data,mux,other,selector]
            literal(negative_select['ref'],'udp_mux2','Z,I0,I1,S')
            boot, wave = (upstream(negative_select,key) for key in ('I0','I1'))
            assert inverted(boot)=='wp_capture_token[6]'
            assert inverted(wave)=='wave_schedule_1__req[12]'
            src=(ROOT/'build/optimization/rtl_sources'/NAME/'encoder/kwt_encoder.sv').read_text()
            assert 'input_capture_generation=wp_boot?wp_capture_token[6]:iw_pipe[0][12]' in src
            assert 'else assign req=iw_pipe[wave_q-1];' in src
            why = 'The actual D cone selects the complement of one of two positive SRAM Q bits. The enabled QN cell restores the positive input-capture bit.'
            checked.append(dict(rtl=rtl,physical_inverted=False,output='QN',net=target,
                reason=why,evidence=dict(cone=cone+[negative_select,boot,wave],cell=cell,pins=p,
                    native_output=segments['pin',cell+'/QN'],native_input=segments['pin',cell+'/D'])))
        elif row['segment']=='shared_memory/memory/stream_write_BAR':
            gate=driver(row['segment'])
            chain=[]
            while gate['pin']=='Z':
                literal(gate['ref'],'buf','Z,I')
                chain.append(gate)
                gate=upstream(gate,'I')
            assert inverted(gate)=='host_dual'
            source=(ROOT/'build/optimization/complete_soc'/NAME/'kwt_shared_dma_icb_sm40.sv').read_text()
            assert '.stream_write(host_dual)' in source
            for alias in row['aliases']:
                assert alias['rtl']=='shared_memory/memory/stream_write'
                record_alias(alias,True,'The literal physical buffers follow the inverter of host_dual, the positive RTL stream-write input.',
                             dict(chain=chain+[gate],native=segments['net',alias['gate']]))
        else:
            assert '/u_bypbuf_fifo/dp_gt0_vec_31_dfflr/qout[0]' in row['segment']
            reg=driver(row['segment'])
            literal(reg['ref'],'buf','Q,n0')
            literal(reg['ref'],'buf','xRN,RDN')
            literal(reg['ref'],'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
            assert reg['pins']['RDN']=='rst_n'
            feedback=upstream(reg,'D')
            literal(feedback['ref'],'or','outA,A1,A2')
            literal(feedback['ref'],'nand','ZN,outA,B')
            assert feedback['pins']['A1']=='lden'
            inverter=upstream(feedback,'A2')
            assert inverted(inverter)==reg['pins']['Q']=='qout[0]'
            data=upstream(feedback,'B')
            literal(data['ref'],'nand','ZN,A1,A2')
            assert {data['pins']['A1'],data['pins']['A2']}=={'lden','dnxt[0]'}
            upstream_rtl=ROOT/'build/server/official_2025/e203_hbirdv2-master/rtl/e203/general/sirv_gnrl_bufs.v'
            assert 'assign i_rdy = (~i_vec[DP-1]);' in upstream_rtl.read_text()
            for alias in row['aliases']:
                negative=alias['rtl'].endswith('/i_rdy')
                assert negative or alias['rtl'].endswith('/qout[0]')
                record_alias(alias,negative,'The reset-zero FIFO full bit is literal positive Q, and the cut-ready output is its complement.',
                             dict(register=reg,feedback=feedback,inverter=inverter,enabled_capture=data))
    draft['pending']=0
    write('corrections-draft',draft)
    write('physical-cell-phase-review',checked)
    write('startup-physical-phase-review',dict(tag=inventory['tag'],reviewed=pending,
        rules=len(draft['aliases']),cell_encodings=len(checked),native_probe_passed=False))
    phases.phase.local_review('assemble')


if __name__=='__main__':
    run()
