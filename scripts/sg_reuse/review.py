"""Resolve the specific remaining phases on the actual slot-reuse checkpoint."""
import itertools
import json
import re
import shutil
import sys

from native import NAME, ROOT, phases
from sr_area_phase_review import native_index


def run(ack_only=False):
    _, report, archive, review = phases.bind('P2', variant=NAME)
    extra = review / 'phase-extra-segments'
    returned = report / 'received/segments/native-evidence' / extra.relative_to(archive)
    for file in returned.iterdir():
        if file.name == 'targets.json':
            assert file.read_bytes() == (extra/file.name).read_bytes()
        else:
            shutil.copyfile(file, extra/file.name)

    def read(name):
        return json.loads((review/(name+'.json')).read_text())

    def write(name, data):
        (review/(name+'.json')).write_text(json.dumps(data, indent=2)+'\n')

    inventory, connections = read('inventory'), read('connectivity')
    result = json.loads((extra/'result.json').read_text())
    assert result['passed'] and result['tag'] == inventory['tag']
    models = {name: body.split('specify')[0] for name, body in re.findall(
        r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule', (review/'vendor-functions.v').read_text())}
    cells, representatives = inventory['cells'], connections['representatives']
    segments = native_index(review/'segments.rpt')
    segments.update(native_index(review/'additional-segments/segments.rpt'))
    segments.update(native_index(extra/'segments.rpt'))
    draft, records = read('corrections-draft'), read('physical-cell-phase-review')
    source = ROOT/'build/optimization/rtl_sources'/NAME/'encoder'
    core = json.loads((report/'baseline-selected.json').read_text())['core_path'].split('.', 1)[1].replace('.', '/')
    memory = 'shared_memory'
    arbiter = memory+'/memory_arbiter'
    reset_cases = {'address', 'words', 'csr_rsp_data', 'csr_rsp_valid', 'csr_rsp_err',
                   'chain', 'chain_error', 'chain_address', 'chain_words'}
    assert 'if(!rst_n)begin address<=0;words<=0;csr_rsp_valid<=0;csr_rsp_err<=0;csr_rsp_data<=0;' in (
        source/'kwt_ld_frontend.sv').read_text()
    assert 'chain<=CH_IDLE;chain_address<=0;chain_words<=0;chain_pending<=0;chain_error<=0;' in (
        source/'kwt_ld_frontend.sv').read_text()
    assert 'wp_emit_token<=0;' in (source/'kwt_encoder.sv').read_text()
    assert 'if(!rst_n) read_bank<=0;' in (ROOT/'rtl/public_encoder/kwt_cpu_tcm_sm40.sv').read_text()

    def rep(net):
        return representatives.get(net, net)

    def port(cell, key):
        return rep(connections['pins'][cell+'/'+key])

    def driver(net):
        row, = connections['drivers'][rep(net)]
        return dict(row, pins={key: value.strip() for key, value in cells[row['cell']]['pins'].items()})

    def literal(ref, primitive, pins):
        assert re.search(r'\b'+primitive+r'\s+(?:\w+\s*)?\(\s*'+
                         r'\s*,\s*'.join(map(re.escape,pins.split(',')))+r'\s*\)', models[ref]), (ref,pins)

    def upstream(cell, key):
        return driver(port(cell,key))

    if ack_only:
        engine, = [name for name in cells if name.endswith('/dma_frontend/loading_dma')]
        for module, prefix in [('shared_memory', 'ld_'), ('soc', 'ld_'),
                               (arbiter, 'b_'), (engine, 'mem_')]:
            parent = module.rpartition('/')[0]
            for signal in ('valid', 'ready'):
                pin = cells[module]['pins'][prefix+'rsp_'+signal].strip()
                assert rep('/'.join(part for part in (parent,pin) if part)) == rep('ld_rsp_'+signal)
        ready, valid = driver('ld_rsp_ready'), driver('ld_rsp_valid')
        assert ready['cell'] == engine+'/pd_active_reg' and ready['pin']=='Q'
        assert 'assign mem_rsp_ready=pd_active;' in (source/'kwt_ld_engine.sv').read_text()
        literal(ready['ref'],'buf','Q,n0')
        literal(valid['ref'],'and','Z,A1,A2')
        assert valid['cell'].startswith(arbiter+'/') and 's_rsp_valid' in valid['pins'].values()
        write('mapped-ack-interface',dict(passed=True,tag=inventory['tag'],variant=NAME,
            valid_expression='dut.ld_rsp_valid',ready_expression='dut.ld_rsp_ready',
            connections=dict(valid=valid,ready=ready,positive_state=ready)))
        print('SG_REUSE_MAPPED_ACK', inventory['tag'], 'positive ready and valid')
        return

    def alias(row, negative, why, evidence):
        draft['aliases'].append(dict(rtl=row['rtl'],gate=row['gate'],inverted=negative,
                                     reason=why,evidence=evidence))

    logic = re.compile(r'\b(buf|not|and|nand|or|nor|xor|xnor|udp_mux2)\s+(?:\w+\s*)?\(([^;()]+)\)')
    bit_ops = {
        'buf': lambda x: x, 'not': lambda x: not x,
        'and': lambda *x: all(x), 'nand': lambda *x: not all(x),
        'or': lambda *x: any(x), 'nor': lambda *x: not any(x),
        'xor': lambda *x: sum(x) % 2 == 1, 'xnor': lambda *x: sum(x) % 2 == 0,
        'udp_mux2': lambda a, b, s: b if s else a,
    }

    def prove(net, leaves, expected):
        cone, cache = {}, {}
        keys = {rep(n): index for index, n in enumerate(leaves)}
        assert len(keys) == len(leaves)

        def expr(name):
            name = rep(name)
            if name in keys:
                return lambda row: row[keys[name]]
            if name in cache:
                return cache[name]
            cell = driver(name)
            cone[cell['cell']] = cell
            equations = {}
            for gate, pins in logic.findall(models[cell['ref']].split('`ifdef')[0]):
                output, *terms = [token.strip() for token in pins.split(',')]
                equations[output] = gate, terms

            def node(pin):
                if pin not in equations:
                    value = cell['pins'][pin]
                    if value in ("1'b0", "1'b1"):
                        return lambda _: value[-1] == '1'
                    return expr(port(cell['cell'],pin))
                gate, terms = equations[pin]
                subs = [node(term) for term in terms]
                return lambda row: bit_ops[gate](*(sub(row) for sub in subs))

            value = cache[name] = node(cell['pin'])
            return value

        actual = expr(net)
        for values in itertools.product((False, True), repeat=len(leaves)):
            assert actual(values) == bool(expected(*values)), (net, leaves, values)
        return dict(leaves=leaves, exhaustive_rows=2**len(leaves), cone=list(cone.values()))

    def names(scope, *bits):
        return [scope+'/'+bit for bit in bits]

    boot = core+'/n61566'
    state_bits = names(core, *('state[%d]' % bit for bit in range(5)))
    def boot_decode(*state):
        return sum(int(v)<<i for i,v in enumerate(state)) == 16
    boot_proof = prove(boot, state_bits, boot_decode)
    cap_select = names(core, 'wp_capture_token[6]', 'wave_schedule_1__req[12]', 'n61566')
    cap_state = names(core, 'n61566', 'wp_capture_token[13]', 'wp_capture_token[8]', 'wp_capture_token[7]')
    cap_net = ['n61966', 'n61965', 'n61964', 'n61963']
    wave_net = ['wave_schedule_1__req[11]', 'wave_schedule_0__execute[11]',
                'wave_schedule_1__execute[11]', 'wave_schedule_2__execute[11]']
    capture_proofs = []
    for q, (target, wave) in enumerate(zip(cap_net,wave_net)):
        capture_proofs.append(prove(core+'/'+target, cap_state+[core+'/'+wave],
            lambda boot, valid, hi, lo, wave: not (valid and 2*hi+lo==q) if boot else not wave))
    addr_bits = names(memory,*('joined_cmd_addr[%d]' % bit for bit in range(19,32)))
    valid_address = prove(memory+'/n786',addr_bits,
                          lambda *bits: sum(int(v)<<i for i,v in enumerate(bits)) == 0x1400)

    pending = read('phase-review-pending')
    boundaries = {row['rtl']: row for row in read('cell-inverted-review-inputs')}
    for row in pending:
        if row['kind'] == 'net_semantics':
            segment = row['segment']
            if segment.endswith('/s_cmd_dma_BAR'):
                evidence = prove(segment,names(arbiter,'held_valid','held_owner','b_cmd_valid',
                                               'a_cmd_valid_BAR','prefer_b'),
                                  lambda held, owner, b, not_a, pref: not (owner if held else b and (not_a or pref)))
                reason = 'The actual grant cone computes the complement of the RTL held/live DMA selection.'
            elif segment == memory+'/memory/en_BAR':
                evidence = prove(segment,names(memory,'host_cmd_ready','host_cmd_valid',
                                               'joined_cmd_ready','joined_cmd_valid','n786'),
                                  lambda hr,hv,jr,jv,ok: not (hr and hv or jr and jv and ok))
                evidence['address_valid'] = valid_address
                reason = 'The actual gate is the complement of physical_accept. A dual host write always has a valid joined read.'
            elif segment.endswith('/write_transposed_BAR'):
                evidence = prove(segment,[boot],lambda wp: not wp)
                evidence['boot_decode'] = boot_proof
                reason = 'The actual queue mode is a buffered complement of the original WP_BOOT state decode.'
            else:
                q = int(re.search(r'return_copies_(\d)',segment)[1])
                evidence = capture_proofs[q]
                reason = 'The return and weight-stage segment is the complement of the original prologue-or-wave capture qualification.'
            for mapped in row['aliases']:
                alias(mapped, True, reason, dict(evidence,native=segments['net',mapped['gate']]))
            draft['reviewed_bar_segments'].append(dict(segment=segment,reason=reason,aliases=len(row['aliases'])))
            continue

        assert row['kind'] == 'cell_encoding', row
        rtl, cell, ref = row['rtl'], row['cell'], row['ref']
        bits = rtl.rsplit('/',1)[-1]
        signal = bits.split('[')[0]
        p = {key:value.strip() for key,value in cells[cell]['pins'].items()}
        output = 'QN' if 'QN' in p else 'Q'
        literal(ref,'not' if output=='QN' else 'buf',output+',n0')
        d = None if p['D'].startswith("1'b") else upstream(cell,'D')
        evidence = dict(cell=cell,pins=p,data_driver=d)
        if signal in reset_cases and '/dma_frontend/' in rtl or signal == 'wp_emit_token':
            assert ref.startswith('DRNQNV')
            literal(ref,'buf','xRN,RDN')
            literal(ref,'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
            evidence['reset'] = prove(port(cell,'RDN'),[cell.rsplit('/',1)[0]+'/rst_n'],lambda rst: rst)
            negative = True
            reason = 'The corresponding RTL state resets to zero. The actual active-low reset clears the primitive and QN is one.'
        elif signal == 'read_bank':
            bit = int(bits.split('[')[1][:-1])
            assert ref=='DSNQV8_12TR40' and p['SDN']=='rst_n'
            literal(ref,'buf','xSN,SDN')
            literal(ref,'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
            scope = cell.rsplit('/',1)[0]
            evidence['capture'] = prove(port(cell,'D'),names(scope,'cs','addr[%d]'%(12+bit),p['Q']),
                                       lambda cs, addr, physical: not addr if cs else physical)
            negative = True
            reason = 'The positive Q has an internal set on reset. Enabled D captures complemented bank address and the hold branch retains that physical Q.'
        elif signal == 'qout_r':
            i = bits[len(signal):]
            scope = cell.rsplit('/',1)[0]
            din = scope+'/dnxt'+i
            if ref=='EDQNV6_12TR40':
                literal(ref,'udp_edff','n0,D,CK,xRN,xSN,E,NOTIFIER')
                assert p['E']=='lden'
                evidence['capture'] = prove(port(cell,'D'),[din],lambda data: not data)
                negative = False
            else:
                literal(ref,'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
                evidence['capture'] = prove(port(cell,'D'),names(scope,'lden', 'dnxt'+i,p[output]),
                    lambda enable, data, q: not (data if enable else q) if output=='QN'
                                            else not data if enable else q)
                negative = output=='Q'
                if output=='QN':
                    assert ref=='DRSNQNV2_12TR40' and p['SDN']=='rst_n' and p['RDN']=="1'b1"
                    literal(ref,'buf','xSN,SDN')
            reason = 'Actual FIFO capture and hold polarity follow the verified D cone and literal vendor storage output.'
        elif signal == 'operand_weight':
            assert bits == 'operand_weight[244]' and ref=='EDGRNQNV6_12TR40' and p['D']=="1'b1"
            literal(ref,'udp_edfft','n0,D,CK,xRN,xSN,E,NOTIFIER')
            literal(ref,'buf','xRN,RN')
            evidence['capture'] = prove(port(cell,'RN'),names(core,'pm_rdata[244]',p['E']),
                                       lambda data,en: not (data and en))
            negative = False
            reason = 'The synchronous active-low clear is !data when enabled. With D fixed at one, QN returns the original weight bit.'
        else:
            assert signal == 'jp_input_return', row
            i = int(bits.split('[')[1][:-1])
            row_id, offset = divmod(i,64)
            q, bit = divmod(offset,16)
            gen = 'ap_input_rows_%d__generation_data' % row_id
            d_inputs = names(core, '%s[%d]'%(gen,bit), '%s[%d]'%(gen,bit+16))
            evidence['source_mux'] = prove(port(cell,'D'),d_inputs+cap_select,
                lambda a,b,prologue,wave,wp: not (b if (prologue if wp else wave) else a))
            if ref == 'EDQNV6_12TR40':
                assert q == 0
                literal(ref,'udp_edff','n0,D,CK,xRN,xSN,E,NOTIFIER')
                evidence['enabled'] = prove(port(cell,'E'),[core+'/'+cap_net[q]],lambda neg: not neg)
            else:
                assert ref == 'DGRSNQNV6_12TR40'
                literal(ref,'udp_edffts','n0,D,clk,xRN,xSN,EN,NOTIFIER')
                literal(ref,'buf','xRN,RN')
                literal(ref,'buf','xSN,SN')
                if q == 0:
                    evidence['sync_hold_one'] = prove(port(cell,'SN'),[core+'/'+cap_net[q]],lambda neg: not neg)
                    evidence['sync_hold_zero'] = prove(port(cell,'RN'),names(core,cap_net[q],bits),
                                                       lambda neg,old_q: not (neg and old_q))
                else:
                    assert i == 240
                    evidence['sync_source_select'] = prove(port(cell,'SN'),cap_state,
                                                           lambda wp,v,h,l: wp and v and h and l)
                    evidence['sync_hold_or_previous'] = prove(port(cell,'RN'),
                        names(core,'ap_input_rows_3__return_copies_3__capture_row',bits,'n21298',
                              'jp_input_return[224]'),
                        lambda take,old,wp,previous: not ((not take and old) or (take and not wp and previous)))
                    evidence['boot_copy'] = prove(core+'/n21298',state_bits,boot_decode)
            negative = False
            reason = 'The actual D mux stores the complement of selected SRAM data, and QN restores its phase. Synchronous overrides implement capture of the preceding tap or hold.'
        cell_row = boundaries[rtl]
        target = cell_row[output+'_net']
        evidence['native_pins'] = {key: segments.get(('pin',cell+'/'+key)) for key in
                                  ('D',output,'RDN','SDN','RN','SN','E') if key in p}
        assert evidence['native_pins'][output] is not None
        records.append(dict(rtl=rtl,physical_inverted=negative,output=output,net=target,
                            reason=reason,evidence=evidence))
        if negative:
            draft['replace_native_cell_aliases'].append(rtl)
            alias(dict(rtl=rtl,gate=target),True,reason,evidence)

    draft['pending'] = 0
    write('physical-cell-phase-review',records)
    write('corrections-draft',draft)
    write('reuse-physical-review',dict(tag=inventory['tag'],pending_rows_resolved=len(pending),
                                     boot_decode=boot_proof,stage_capture=capture_proofs,
                                     aliases=len(draft['aliases']),
                                     replaced_cells=len(draft['replace_native_cell_aliases'])))
    phases.phase.local_review('assemble')


if __name__ == '__main__':
    run(ack_only=sys.argv[1:] == ['ack'])
