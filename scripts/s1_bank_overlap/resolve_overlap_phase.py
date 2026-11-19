"""Close the remaining phase cases on each independently mapped bank candidate."""
import json
import re
import shutil
import sys

from phase_overlap import ROOT, bind, phase


def resolve(mode, native=False, variant=None):
    name, report, archive, review = bind(mode, native=native, variant=variant)
    extra = review / 'phase-extra-segments'
    if not native:
        received = report / 'received/segments/native-evidence' / extra.relative_to(archive)
        for path in received.iterdir():
            if path.name == 'targets.json':
                assert path.read_bytes() == (extra / path.name).read_bytes()
            else:
                shutil.copyfile(path, extra / path.name)

    def read(file):
        return json.loads((review / file).read_text())

    def write(file, value):
        (review / file).write_text(json.dumps(value, indent=2) + '\n')

    inventory, connection = read('inventory.json'), read('connectivity.json')
    result = read('phase-extra-segments/result.json')
    assert result['passed'] and result['variant'] == name and result['tag'] == inventory['tag']
    cells, representatives = inventory['cells'], connection['representatives']
    models = {m[1]: m[2].split('specify')[0] for m in re.finditer(
        r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule', (review / 'vendor-functions.v').read_text())}
    pending = read('phase-review-pending.json')
    draft, reviewed = read('corrections-draft.json'), read('physical-cell-phase-review.json')
    inverted_rows = {r['rtl']: r for r in read('cell-inverted-review-inputs.json')}

    def representative(net):
        return representatives.get(net, net)

    def pins(cell):
        return {pin: value.strip() for pin, value in cells[cell]['pins'].items()}

    def pin_net(cell, pin):
        return representative(connection['pins'][cell + '/' + pin])

    def driver(net):
        row, = connection['drivers'][representative(net)]
        return dict(row, pins=pins(row['cell']))

    def upstream(cell, pin):
        return driver(pin_net(cell, pin))

    def literal(ref, primitive, args):
        assert re.search(r'\b' + primitive + r'\s+(?:\w+\s*)?\(\s*' +
                         r'\s*,\s*'.join(map(re.escape, args.split(','))) + r'\s*\)', models[ref]), ref

    def inverse_input(row):
        literal(row['ref'], 'not', 'ZN,I')
        return row['pins']['I']

    def unary_root(net):
        steps, inverted = [], False
        while len(connection['drivers'].get(net, [])) == 1:
            row = driver(net)
            if 'I' not in row['pins'] or row['pin'] not in ('Z', 'ZN'):
                break
            negative = row['pin'] == 'ZN'
            literal(row['ref'], 'not' if negative else 'buf', row['pin'] + ',I')
            steps.append(row)
            inverted ^= negative
            net = pin_net(row['cell'], 'I')
        return net, inverted, steps

    def input_select(row, bit):
        physical_row, offset = bit // 32, bit % 16
        prefix = 'ap_input_rows_%d__generation_data' % physical_row
        assert row['pins']['A1'] == '%s[%d]' % (prefix, offset)
        assert row['pins']['B2'] == '%s[%d]' % (prefix, offset + 16)
        literal(row['ref'], 'and', 'outA,A2,A1')
        literal(row['ref'], 'and', 'outB,B2,B1')
        literal(row['ref'], 'nor', 'ZN,outA,outB')
        return [upstream(row['cell'], pin) for pin in ('A2', 'B1')]

    def add_alias(rtl, gate, negative, reason, data):
        draft['aliases'].append(dict(rtl=rtl, gate=gate, inverted=negative,
                                    reason=reason, evidence=data))

    for item in pending:
        if item['kind'] == 'net_semantics':
            rows = item['aliases']
            dr, = item['drivers']
            cell = dr['cell']
            if item['segment'].endswith('/s_cmd_dma_BAR'):
                literal(dr['ref'], 'buf', 'Z,I')
                outer = upstream(cell, 'I')
                literal(outer['ref'], 'and', 'OUT0,B1,B2')
                literal(outer['ref'], 'not', 'OUT1,A')
                literal(outer['ref'], 'nor', 'ZN,OUT0,OUT1')
                assert outer['pins']['B1'] == 'b_cmd_valid'
                stored = upstream(outer['cell'], 'A')
                live = upstream(outer['cell'], 'B2')
                literal(stored['ref'], 'nand', 'ZN,A1,A2')
                literal(live['ref'], 'and', 'OUT0,A1,A2')
                literal(live['ref'], 'nor', 'ZN,OUT0,B')
                assert {stored['pins'][p] for p in ('A1', 'A2')} == {'held_valid', 'held_owner'}
                assert live['pins']['B'] == 'held_valid'
                cpu, prefer = (upstream(live['cell'], pin) for pin in ('A1', 'A2'))
                assert inverse_input(cpu) == 'a_cmd_valid_BAR' and inverse_input(prefer) == 'prefer_b'
                data = dict(chain=[dr, outer, stored, live, cpu, prefer])
                reason = 'The literal cone outputs !(held_valid && held_owner || !held_valid && b_cmd_valid && (!a_cmd_valid || prefer_b)), the complement of the RTL grant.'
            elif item['segment'].endswith('/icb2mem_dfflr/lden_BAR'):
                assert {r['rtl'].rsplit('/', 2)[-2] for r in rows} == {'icb2mem_dfflr', 'icb2itcm_dfflr'}
                literal(dr['ref'], 'or', 'Z,A1,A2')
                valid, ready = (upstream(cell, pin) for pin in ('A1', 'A2'))
                literal(valid['ref'], 'and', 'OUT0,A1,A2')
                literal(valid['ref'], 'nor', 'ZN,OUT0,B')
                literal(ready['ref'], 'udp_mux2', 'z,I0,I1,S')
                literal(ready['ref'], 'not', 'ZN,z')
                assert {ready['pins'][k] for k in ('I0', 'I1')} == {'ifu2biu_icb_cmd_ready', 'ifu2itcm_icb_cmd_ready'}
                source = ROOT / 'build/server/official_2025/e203_hbirdv2-master/rtl/e203/core/e203_ifu_ift2icb.v'
                text = source.read_text()
                for token in ('ifu_icb_cmd_hsked = ifu_icb_cmd_valid & ifu_icb_cmd_ready',
                              'icb2itcm_dfflr(ifu_icb_cmd_hsked', 'icb2mem_dfflr (ifu_icb_cmd_hsked'):
                    assert token in text
                data = dict(cone=[dr, valid, ready], valid_terms=[upstream(valid['cell'], p) for p in ('A1', 'A2', 'B')],
                            source=source.relative_to(ROOT).as_posix())
                reason = 'Both original lden ports receive the same valid-and-ready handshake. The actual OR combines the complements of the command valid and the selected ITCM/BIU ready.'
            elif item['segment'].endswith('/rowbuf_cnt_d_dfflr/qout_0__BAR') and variant:
                assert dr['ref'] == 'DSNQV8_12TR40' and pins(cell)['SDN'] == 'rst_n'
                literal(dr['ref'], 'buf', 'xSN,SDN')
                literal(dr['ref'], 'buf', 'Q,n0')
                literal(dr['ref'], 'udp_dff', 'n0,D,clk,xRN,xSN,NOTIFIER')
                feedback = upstream(cell, 'D')
                literal(feedback['ref'], 'or', 'outA,A1,A2')
                literal(feedback['ref'], 'and', 'Z,outA,B')
                assert feedback['pins']['A1'] == 'lden' and feedback['pins']['A2'] == 'qout_0__BAR'
                capture = upstream(feedback['cell'], 'B')
                literal(capture['ref'], 'nand', 'ZN,A1,A2')
                assert {capture['pins'][k] for k in ('A1','A2')} == {'lden','dnxt[0]'}
                data = dict(register=dr, feedback=feedback, capture=capture)
                reason = 'Internal reset sets Q to one. On lden, D takes !dnxt, and otherwise D holds Q. Physical Q is the complement of the reset-zero RTL state.'
            else:
                raise ValueError(item)
            for row in rows:
                add_alias(row['rtl'], row['gate'], True, reason, data)
            draft['reviewed_bar_segments'].append(dict(segment=item['segment'], reason=reason, aliases=len(rows)))
            continue

        assert item['kind'] == 'cell_encoding'
        rtl, cell, ref = item['rtl'], item['cell'], item['ref']
        p = pins(cell)
        signal = rtl.rsplit('/', 1)[-1]
        output = 'QN' if 'QN' in p else 'Q'
        literal(ref, 'not' if output == 'QN' else 'buf', output + ',n0')
        data = dict(cell=cell, ref=ref, pins=p)

        if signal.startswith('qout_r['):
            bit = signal[6:]
            dnxt, qout = 'dnxt' + bit, 'qout' + bit
            if ref.startswith(('EDQNV', 'EDRNQNV')):
                dr = upstream(cell, 'D')
                assert inverse_input(dr) == dnxt and p['QN'] in (qout, 'qout_' + bit[1:-1] + '_')
                parent = cell.rsplit('/', 1)[0]
                expected_enable = representative(parent + '/lden')
                enable = unary_root(pin_net(cell, 'E'))
                assert enable[:2] == unary_root(expected_enable)[:2]
                assert 'RDN' not in p or p['RDN'] == "1'b1"
                literal(ref, 'udp_edff', 'n0,D,CK,xRN,xSN,E,NOTIFIER')
                data.update(capture=dr, enable=enable)
                negative, reason = False, 'Inverted dnxt at D and a literal QN inversion restore the FIFO value.'
            elif ref.startswith('EDGRNQNV'):
                dr = upstream(cell, 'RN')
                literal(dr['ref'], 'nand', 'ZN,A1,A2')
                assert {dr['pins'][k] for k in ('A1', 'A2')} == {'lden', dnxt}
                assert p['D'] == "1'b1" and p['QN'] == qout
                assert unary_root(pin_net(cell, 'E'))[:2] == unary_root(pin_net(dr['cell'], 'A1'))[:2]
                literal(ref, 'udp_edfft', 'n0,D,CK,xRN,xSN,E,NOTIFIER')
                data.update(synchronous_reset=dr, enable=unary_root(pin_net(cell, 'E')))
                negative, reason = False, 'When lden is high, RN is !dnxt and D is one. The synchronous reset and output inversion give QN=dnxt. When lden is low, RN is high and E is low.'
            elif ref.startswith('DQV'):
                mux = upstream(cell, 'D')
                literal(mux['ref'], 'udp_mux2', 'Z,I0,I1,S')
                assert mux['pins']['S'] == 'lden' and mux['pins']['I0'] == p['Q']
                dr = upstream(mux['cell'], 'I1')
                assert inverse_input(dr) == dnxt
                literal(ref, 'udp_dff', 'n0,D,clk,xRN,xSN,NOTIFIER')
                data.update(mux=mux, capture=dr)
                negative, reason = True, 'The enabled D mux stores inverted dnxt on the literal positive Q. The hold branch feeds that same Q.'
            else:
                raise ValueError(item)
        elif variant and signal.startswith('jp_input_return['):
            bit = int(signal.split('[')[1][:-1])
            previous = 'jp_input_return[%d]' % (bit - 16)
            assert bit // 16 % 4 in (1, 3) and p['QN'] == signal
            dr = upstream(cell, 'D')
            if ref == 'EDQNV6_12TR40':
                assert inverse_input(dr) == previous
                prior = upstream(dr['cell'],'I')
                assert prior['ref'] == 'DQV8_12TR40' and prior['pins']['Q'] == previous
                literal(prior['ref'],'buf','Q,n0')
                literal(ref,'udp_edff','n0,D,CK,xRN,xSN,E,NOTIFIER')
                data.update(capture=dr, previous=prior, enable=upstream(cell,'E'))
                reason = 'Positive preceding tap drives the literal inverter at D. The enabled QN cell restores the positive previous tap.'
            elif ref == 'DQNV6_12TR40':
                literal(ref,'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
                literal(dr['ref'],'or','outA,A1,A2')
                literal(dr['ref'],'and','Z,outA,B')
                sample, hold = (upstream(dr['cell'],pin) for pin in ('A2','B'))
                assert inverse_input(sample) == previous
                literal(hold['ref'],'nand','ZN,A1,A2')
                assert {hold['pins'][k] for k in ('A1','A2')} == {dr['pins']['A1'],signal}
                enable = unary_root(pin_net(dr['cell'],'A1'))
                assert enable[1] and driver(enable[0])['cell'].endswith('/iw_pipe_reg_3__11_')
                data.update(capture=dr, previous=sample, hold=hold, enable=enable)
                reason = 'With !capture high, OA/NAND feeds !QN to retain the bit. On capture D is inverted previous-tap data, restored at QN.'
            else:
                raise ValueError(item)
            negative = False
        elif signal.startswith(('jp_input_return[', 'operand_weight[')):
            bit = int(signal.split('[')[1][:-1])
            is_input = signal.startswith('jp_')
            if ref.startswith('EDGRNQNV'):
                assert p['D'] == "1'b1" and p['QN'] in (signal, signal.replace('[','_').replace(']','_'))
                dr = upstream(cell, 'RN')
                if is_input:
                    data['input_selects'] = input_select(dr, bit)
                else:
                    literal(dr['ref'], 'nand', 'ZN,A1,A2')
                    assert dr['pins']['A1'] == 'pm_rdata[%d]' % bit
                    assert unary_root(pin_net(dr['cell'], 'A2'))[:2] == unary_root(pin_net(cell, 'E'))[:2]
                literal(ref, 'udp_edfft', 'n0,D,CK,xRN,xSN,E,NOTIFIER')
                data.update(synchronous_reset=dr, enable=upstream(cell, 'E'))
                negative, reason = False, 'During capture the selected positive input is inverted at RN. With D=1 the synchronous-reset cell exposes the original value on QN.'
            elif ref.startswith('DQNV'):
                dr = upstream(cell, 'D')
                literal(ref, 'udp_dff', 'n0,D,clk,xRN,xSN,NOTIFIER')
                literal(dr['ref'], 'or', 'outA,A1,A2')
                data['capture'] = dr
                selected = upstream(dr['cell'], 'B')
                data['selected_data'] = selected
                if is_input:
                    data['input_selects'] = input_select(selected, bit)
                else:
                    literal(selected['ref'], 'nand', 'ZN,A1,A2')
                    assert selected['pins']['A1'] == 'pm_rdata[%d]' % bit
                    assert unary_root(pin_net(dr['cell'], 'A1'))[:2] == unary_root(pin_net(selected['cell'], 'A2'))[:2]
                negative = dr['pin'] == 'ZN'
                if negative:
                    literal(dr['ref'], 'nand', 'ZN,outA,B')
                    assert dr['pins']['A2'] == p['QN']
                    reason = 'The OAI undoes the selected-data inversion at D on capture. Literal QN is the negative of the RTL bit. Feedback retains the encoded state.'
                else:
                    literal(dr['ref'], 'and', 'Z,outA,B')
                    feedback = upstream(dr['cell'], 'A2')
                    assert inverse_input(feedback) == p['QN'] == signal
                    data['feedback'] = feedback
                    reason = 'The OA supplies the inverted selected bit at D on capture. Literal QN restores the positive RTL bit.'
            else:
                raise ValueError(item)
        elif signal.startswith('read_bank[') and '/u_e203_itcm_ram/' in rtl:
            bit = int(signal[10:-1])
            assert p['RDN'] == 'rst_n'
            literal(ref, 'buf', 'xRN,RDN')
            literal(ref, 'udp_dff', 'n0,D,clk,xRN,xSN,NOTIFIER')
            dr = upstream(cell, 'D')
            if 'I1' in dr['pins']:
                literal(dr['ref'], 'udp_mux2', 'z,I0,I1,S')
                literal(dr['ref'], 'not', 'ZN,z')
                assert dr['pins']['S'] == 'cs' and dr['pins']['I0'] == p['QN']
                address = upstream(dr['cell'], 'I1')
                assert inverse_input(address) == 'addr[%d]' % (12 + bit)
            else:
                literal(dr['ref'], 'or', 'outA,A1,A2')
                literal(dr['ref'], 'nand', 'ZN,outA,B')
                assert dr['pins']['A1'] == 'cs' and dr['pins']['A2'] == p['QN']
                inv = upstream(dr['cell'], 'B')
                inverse_input(inv)
                address = upstream(inv['cell'], 'I')
                literal(address['ref'], 'and', 'Z,A1,A2')
                assert {address['pins'][k] for k in ('A1', 'A2')} == {'cs', 'addr[%d]' % (12 + bit)}
                data['invert'] = inv
            data.update(capture=dr, address=address)
            negative, reason = True, 'RDN resets the internal state to zero. Selected positive address is captured at D on cs, so physical QN is negative RTL bank state.'
        else:
            raise ValueError(item)

        row = inverted_rows[rtl]
        assert row['gate'] == cell
        net = row[output + '_net']
        reviewed.append(dict(rtl=rtl, physical_inverted=negative, output=output, net=net,
                             reason=reason, evidence=data))
        if negative:
            draft['replace_native_cell_aliases'].append(rtl)
            add_alias(rtl, net, True, reason, data)

    engine, = [path for path in cells if path.endswith('/dma_frontend/loading_dma')]
    inverted_ack_ready = 'ld_rsp_ready_BAR' in pins('shared_memory')
    ready_pin = 'ready_BAR' if inverted_ack_ready else 'ready'
    for module, prefix in [('shared_memory', 'ld_'), ('soc', 'ld_'),
                           ('shared_memory/memory_arbiter', 'b_'), (engine, 'mem_')]:
        parent = module.rpartition('/')[0]
        for direction in ('valid', ready_pin):
            connected = pins(module)[prefix + 'rsp_' + direction]
            actual = '/'.join(part for part in (parent, connected) if part)
            assert representative(actual) == representative('ld_rsp_' + direction.split('_')[0])
    ready, valid = driver('ld_rsp_ready'), driver('ld_rsp_valid')
    if inverted_ack_ready:
        inverse_input(ready)
    state = upstream(ready['cell'], 'I') if inverted_ack_ready else ready
    assert state['cell'] == engine + '/pd_active_reg'
    literal(state['ref'], 'buf', 'Q,n0')
    literal(valid['ref'], 'and', 'Z,A1,A2')
    assert 's_rsp_valid' in valid['pins'].values()
    write('mapped-ack-interface.json', dict(passed=True, tag=inventory['tag'], variant=name,
          valid_expression='dut.ld_rsp_valid', ready_expression=('!' if inverted_ack_ready else '')+'dut.ld_rsp_ready',
          connections=dict(valid=valid, ready=ready, positive_state=state)))

    prefix = {path: row for path, row in cells.items() if path.startswith(
        ('shared_memory/input_committed_reg_', 'shared_memory/input_background_phase_reg',
         'shared_memory/parameter_committed_reg_', 'shared_memory/shift_committed_reg_'))}
    assert len(prefix) == 34
    for row in prefix.values():
        assert 'Q' in row['pins'] and 'QN' not in row['pins']
        literal(row['ref'], 'buf', 'Q,n0')
    write('overlap-state-physical-review.json', dict(tag=inventory['tag'], positive_Q_registers=prefix))
    write('resolved-overlap-phase-inputs.json', pending)
    draft['pending'] = 0
    write('corrections-draft.json', draft)
    write('physical-cell-phase-review.json', reviewed)
    print('BANK_PHASE_RESOLVED', name, len(pending), len(draft['aliases']))


if __name__ == '__main__':
    mode = sys.argv[1]
    if sys.argv[2:] == ['--native']:
        bind(mode, native=True)
        phase.local_review('inspect')
        resolve(mode, native=True)
        phase.local_review('assemble')
    else:
        resolve(mode)
