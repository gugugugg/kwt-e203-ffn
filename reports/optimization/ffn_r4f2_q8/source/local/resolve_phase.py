"""Resolve phase exceptions using this candidate's actual library and wired cones."""
from collections import Counter
import json
import re

from phase import REVIEW


def read(name):
    return json.loads((REVIEW / name).read_text())


def write(name, data):
    (REVIEW / name).write_text(json.dumps(data, indent=2) + '\n')


def resolve():
    inv, conn = read('inventory.json'), read('connectivity.json')
    cells, reps = inv['cells'], conn['representatives']
    draft = read('corrections-draft.json')
    pending = read('phase-review-pending.json')
    reviewed = read('physical-cell-phase-review.json')
    native = read('phase-extra-segments/result.json')
    assert native['passed'] and native['tag'] == inv['tag']
    original = {row['rtl']: row for row in read('cell-inverted-review-inputs.json')}
    vendor = (REVIEW / 'vendor-functions.v').read_text()
    models = {m[1]: m[2].split('specify')[0] for m in re.finditer(
        r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule', vendor)}

    def rep(net):
        return reps.get(net, net)

    def driver(net):
        row, = conn['drivers'][rep(net)]
        return dict(row, pins={pin: value.strip() for pin, value in cells[row['cell']]['pins'].items()})

    def literal(cell, expression):
        assert re.search(expression, models[cell['ref']]), cell


    def unary_root(net):
        chain = []
        phase = False
        while len(conn['drivers'].get(rep(net), [])) == 1:
            step = driver(net)
            if not re.fullmatch(r'(?:CLKINV|CLKBUF|BUF)\w+', step['ref']):
                break
            negative = step['pin'] == 'ZN'
            literal(step, r'\bnot\s+\w+\s*\(ZN, I\)' if negative else r'\bbuf\s+\w+\s*\(Z, I\)')
            phase ^= negative
            chain.append(step)
            net = conn['pins'][step['cell'] + '/I']
        return dict(root=rep(net), negative=phase, chain=chain)

    arbiter = 'shared_memory/memory_arbiter'
    for exception in pending:
        if exception['kind'] == 'net_semantics':
            rtl = arbiter + '/s_cmd_dma'
            alias, = exception['aliases']
            assert alias['rtl'] == rtl and exception['segment'] == rtl + '_BAR'
            names = ['s_cmd_dma_BAR', 'n12', 'n18', 'n10', 'n9', 'n8']
            expected = [
                ({'I':'n12','Z':'s_cmd_dma_BAR'}, r'buf\s+\w+\s*\(Z, I\)'),
                ({'B1':'b_cmd_valid','B2':'n10','A':'n18','ZN':'n12'},
                 r'and\s+\w+\(OUT0, B1, B2\);\s+not\s+\w+\(OUT1, A\);\s+nor\s+\w+\(ZN, OUT0, OUT1\)'),
                ({'A1':'held_valid','A2':'held_owner','ZN':'n18'}, r'nand\s+\w+\(ZN, A1, A2\)'),
                ({'A1':'n9','A2':'n8','B':'held_valid','ZN':'n10'},
                 r'and\s+\w+\(OUT0, A1, A2\);\s+nor\s+\w+\(ZN, OUT0, B\)'),
                ({'I':'a_cmd_valid_BAR','ZN':'n9'}, r'not\s+\w+\s*\(ZN, I\)'),
                ({'I':'prefer_b','ZN':'n8'}, r'not\s+\w+\s*\(ZN, I\)')]
            cone = [driver(arbiter + '/' + name) for name in names]
            for step, (pins, primitive) in zip(cone, expected):
                assert step['pins'] == pins, step
                literal(step, primitive)
            draft['aliases'].append(dict(rtl=rtl, gate=alias['gate'], inverted=True,
                reason='Literal cone is the complement of held_valid ? held_owner : (b_cmd_valid && (!a_cmd_valid || prefer_b)).',
                evidence=dict(cone=cone)))
            continue
        assert exception['kind'] == 'cell_encoding', exception
        rtl = exception['rtl']
        cell = original[rtl]
        path, ref = cell['gate'], cell['ref']
        parent = path.rsplit('/', 1)[0] + '/'
        pins = {pin: val.strip() for pin, val in cell['pins'].items()}
        short = rtl.rsplit('/', 1)[-1]
        cone = {}
        if ref == 'EDQNV6_12TR40' and short.startswith('qout_r['):
            d = cone['D'] = driver(parent + pins['D'])
            literal(cell, r'not\s+\w+\s*\(QN, n0\)')
            literal(d, r'not\s+\w+\s*\(ZN, I\)')
            assert pins['E'] == 'lden' and d['pins']['I'] == short.replace('qout_r', 'dnxt')
            assert pins['QN'] == short.replace('qout_r', 'qout')
            inverted = False
            reason = 'Enabled D capture is the literal inverse of dnxt. QN restores the original FIFO state.'
        elif ref == 'DQV0_12TR40' and short == 'qout_r[57]':
            d = cone['D'] = driver(parent + pins['D'])
            literal(cell, r'udp_dff\s+\w+\s*\(n0')
            literal(d, r'udp_mux2\s*\(Z, I0, I1, S\)')
            assert d['pins']['S'] == 'lden' and d['pins']['I0'] == pins['Q']
            cone['enabled_data'] = driver(parent + d['pins']['I1'])
            cone['logical_output'] = driver(parent + 'qout[57]')
            for step in (cone['enabled_data'], cone['logical_output']):
                literal(step, r'not\s+\w+\s*\(ZN, I\)')
            assert cone['enabled_data']['pins']['I'] == 'dnxt[57]'
            assert cone['logical_output']['pins']['I'] == pins['Q']
            inverted = True
            reason = 'The mux captures inverted dnxt[57] and holds the inverse state. qout[57] inverts the physical Q.'
        elif ref == 'EDGRNQNV6_12TR40' and short == 'operand_weight[135]':
            literal(cell, r'udp_edfft\s+\w+\s*\(n0, D, CK, xRN, xSN, E, NOTIFIER\)')
            literal(cell, r'not\s+\w+\s*\(QN, n0\)')
            assert pins['D'] == "1'b1" and pins['QN'] == short
            rn = cone['RN'] = driver(parent + pins['RN'])
            literal(rn, r'nand\s+\w+\(ZN, A1, A2\)')
            assert rn['pins']['A1'] == 'pm_rdata[135]'
            gate = parent + 'weight_stage_gate/cell_gate'
            assert rep(conn['pins'][path + '/CK']) == rep(conn['pins'][gate + '/Q'])
            cone['enable_paths'] = [unary_root(net) for net in (
                parent + pins['E'], parent + rn['pins']['A2'], conn['pins'][gate + '/E'])]
            assert len({(x['root'], x['negative']) for x in cone['enable_paths']}) == 1, cone
            inverted = False
            reason = 'At the enabled sampling edge D is one and synchronous active-low RN is the inverse of the macro bit. QN restores that bit.'
        else:
            raise RuntimeError('Unresolved actual cell phase: ' + rtl)
        output = 'Q' if 'Q_net' in cell else 'QN'
        net = cell[output + '_net']
        evidence = dict(cell=path, ref=ref, pins=pins, cone=cone)
        reviewed.append(dict(rtl=rtl, physical_inverted=inverted, output=output,
                             net=net, reason=reason, evidence=evidence))
        if inverted:
            draft['replace_native_cell_aliases'].append(rtl)
            draft['aliases'].append(dict(rtl=rtl, gate=net, inverted=True, reason=reason, evidence=evidence))

    engine, = [name for name in cells if name.endswith('/dma_frontend/loading_dma')]
    ports = {}
    for field in ('valid', 'ready'):
        signal = 'ld_rsp_' + field
        bp, ep = 'b_rsp_' + field, 'mem_rsp_' + field
        for path in ('shared_memory', 'soc'):
            assert cells[path]['pins'][signal].strip() == signal
        assert cells[arbiter]['pins'][bp].strip() == signal
        assert rep(engine.rsplit('/', 1)[0] + '/' + cells[engine]['pins'][ep].strip()) == rep(signal)
        ports[field] = dict(signal=signal, arbiter_pin=arbiter + '/' + bp, engine_pin=engine + '/' + ep,
                            driver=driver(signal), physical_inverted=False)
    assert ports['ready']['driver']['cell'] == engine + '/pd_active_reg'
    literal(ports['ready']['driver'], r'buf\s+\w+\s*\(Q, n0\)')
    assert ports['valid']['driver']['pins']['A1'] == 's_rsp_valid'
    literal(ports['valid']['driver'], r'and\s+\w+\s*\(Z, A1, A2\)')

    ring = {path: cell for path, cell in cells.items() if '/output_queue/held_' in path
            and path.rsplit('/', 1)[-1].startswith(('held_data_reg', 'held_head_reg', 'held_tail_reg', 'held_count_reg'))}
    generations = {path: cell for path, cell in cells.items() if '/output_queue/' in path and
                   path.rsplit('/', 1)[-1].startswith(('generation_state_reg', 'pending_generation_reg'))}
    assert len(ring) == 71 and len(generations) == 5
    for cell in list(ring.values()) + list(generations.values()):
        literal(cell, r'buf\s+\w+\s*\(Q, n0\)')
    write('result-ring-physical-state.json', dict(tag=inv['tag'], total_positive_Q_registers=len(ring),
          actual_cell_references=dict(Counter(cell['ref'] for cell in ring.values())),
          data_words=4, bits_per_word=16, unknown_activity_preserved=True,
          ring=ring, output_generation=generations))
    draft['pending'] = 0
    write('resolved-q8-phase-inputs.json', pending)
    write('corrections-draft.json', draft)
    write('physical-cell-phase-review.json', reviewed)
    write('mapped-ack-interface.json', dict(passed=True, tag=inv['tag'], variant=inv['variant'],
          valid_expression='dut.ld_rsp_valid', ready_expression='dut.ld_rsp_ready', connections=ports))
    print('Q8_PHASE_RESOLVED', len(pending), len(draft['aliases']), flush=True)


if __name__ == '__main__':
    resolve()
