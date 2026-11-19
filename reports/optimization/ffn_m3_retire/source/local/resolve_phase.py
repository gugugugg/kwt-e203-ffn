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

    def upstream(net, expected):
        chain = []
        while rep(net) != rep(expected):
            step = driver(net)
            literal(step, r'\bbuf\s+\w+\s*\(\s*Z\s*,\s*I\s*\)')
            chain.append(step)
            net = conn['pins'][step['cell'] + '/I']
        return chain

    for exception in pending:
        assert exception['kind'] == 'cell_encoding', exception
        rtl = exception['rtl']
        cell = original[rtl]
        path, ref = cell['gate'], cell['ref']
        parent = path.rsplit('/', 1)[0] + '/'
        pins = {pin: val.strip() for pin, val in cell['pins'].items()}
        short = rtl.rsplit('/', 1)[-1]
        d = driver(parent + pins['D'])
        cone = dict(D=d)
        if ref == 'EDQNV6_12TR40' and short.startswith('qout_r['):
            literal(cell, r'not\s+\w+\s*\(QN, n0\)')
            literal(d, r'not\s+\w+\s*\(ZN, I\)')
            assert pins['E'] == 'lden' and d['pins']['I'] == short.replace('qout_r', 'dnxt')
            assert pins['QN'] == short.replace('qout_r', 'qout')
            inverted = False
            reason = 'On enabled capture D is the literal inverse of dnxt. QN restores the original FIFO state.'
        elif ref == 'DQV0_12TR40' and short == 'qout_r[63]':
            literal(cell, r'udp_dff\s+\w+\s*\(n0')
            literal(d, r'udp_mux2\s*\(Z, I0, I1, S\)')
            assert d['pins']['S'] == 'lden' and d['pins']['I0'] == pins['Q']
            cone['enabled_data'] = driver(parent + d['pins']['I1'])
            cone['logical_output'] = driver(parent + 'qout[63]')
            for step in (cone['enabled_data'], cone['logical_output']):
                literal(step, r'not\s+\w+\s*\(ZN, I\)')
            assert cone['enabled_data']['pins']['I'] == 'dnxt[63]'
            assert cone['logical_output']['pins']['I'] == pins['Q']
            inverted = True
            reason = 'The enabled mux captures the inverse of dnxt[63]. The hold leg keeps the inverse state, and qout[63] is its literal inverse.'
        elif ref == 'EDRNQNV6_12TR40' and short == 'stored_rsp_valid':
            literal(cell, r'not\s+\w+\s*\(QN, n0\)')
            cone['logical_output'] = driver(parent + short)
            literal(cone['logical_output'], r'not\s+\w+\s*\(ZN, I\)')
            assert cone['logical_output']['pins']['I'] == pins['QN']
            assert pins['E'] == "1'b1"
            cone['reset'] = []
            reset = parent + pins['RDN']
            while rep(reset) != rep(parent + 'rst_n'):
                step = driver(reset)
                literal(step, r'(?:not|buf)\s+\w+\s*\(\s*Z[N]?\s*,\s*I\s*\)')
                cone['reset'].append(step)
                reset = conn['pins'][step['cell'] + '/I']
            assert sum('ZN' in s['pins'] for s in cone['reset']) % 2 == 0
            inverted = True
            reason = 'The physical QN drives the literal inverter producing logical stored_rsp_valid. Its reset pin sees the original active-low reset through a non-inverting chain.'
        elif ref == 'DQNV6_12TR40' and short == 'jp_input_return[73]':
            literal(cell, r'not\s+\w+\s*\(QN, n0\)')
            literal(d, r'nand\s+\w+\s*\(ZN, outA, B\)')
            assert d['ref'] == 'OAI21V0_12TR40'
            enable = parent + 'n910'
            gate = parent + 'ap_input_rows_2__return_copies_0__return_gate/cell_gate'
            cone['capture_clock_gate'] = dict(cell=gate, **cells[gate])
            cone['enable_to_gate'] = upstream(conn['pins'][gate + '/E'], enable)
            cone['enable_to_D'] = upstream(parent + d['pins']['A1'], enable)
            cone['input_nand'] = driver(parent + d['pins']['B'])
            assert cone['input_nand']['pins']['A1'] == 'ap_input_rdata[41]'
            literal(cone['input_nand'], r'nand\s+\w+\s*\(\s*ZN\s*,\s*A1\s*,\s*A2\s*\)')
            cone['enable_to_input'] = upstream(parent + cone['input_nand']['pins']['A2'], enable)
            feedback = parent + d['pins']['A2']
            cone['feedback'] = []
            for _ in range(2):
                step = driver(feedback)
                literal(step, r'not\s+\w+\s*\(ZN, I\)')
                cone['feedback'].append(step)
                feedback = conn['pins'][step['cell'] + '/I']
            assert rep(feedback) == rep(parent + pins['QN'])
            inverted = True
            reason = 'With the gate enable asserted, the OAI output D equals positive input macro bit 41. QN inverts the captured value. With enable low the D path feeds back the inverse of QN.'
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
    arbiter = 'shared_memory/memory_arbiter'
    ports = {}
    for field, suffix in [('valid', ''), ('ready', '_BAR')]:
        signal = 'ld_rsp_' + field
        bus = signal + suffix
        bp, ep = 'b_rsp_' + field + suffix, 'mem_rsp_' + field + suffix
        for path in ('shared_memory', 'soc'):
            assert cells[path]['pins'][bus].strip() == signal
        assert cells[arbiter]['pins'][bp].strip() == bus
        assert rep(engine.rsplit('/', 1)[0] + '/' + cells[engine]['pins'][ep].strip()) == rep(signal)
        ports[field] = dict(signal=signal, arbiter_pin=arbiter + '/' + bp, engine_pin=engine + '/' + ep)
    ready = driver('ld_rsp_ready')
    assert ready['cell'].startswith(engine + '/') and ready['pins'] == dict(I='busy', ZN='busy_BAR')
    literal(ready, r'not\s+\w+\s*\(ZN, I\)')
    active = driver(engine + '/busy')
    assert active['cell'].endswith('/pd_active_reg') and active['pin'] == 'Q'
    ports['ready'].update(driver=ready, active_state=active, physical_inverted=True)
    ports['valid'].update(driver=driver('ld_rsp_valid'), physical_inverted=False)

    ring = {path: cell for path, cell in cells.items() if '/output_queue/held_' in path
            and path.rsplit('/', 1)[-1].startswith(('held_data_reg', 'held_head_reg', 'held_tail_reg', 'held_count_reg'))}
    assert len(ring) == 71
    for cell in ring.values():
        literal(cell, r'buf\s+\w+\s*\(Q, n0\)')
    write('result-ring-physical-state.json', dict(tag=inv['tag'], total_positive_Q_registers=len(ring),
          actual_cell_references=dict(Counter(cell['ref'] for cell in ring.values())),
          data_words=4, bits_per_word=16, direct_array_state_in_case1_saif=False,
          state=dict(ring)))
    draft['pending'] = 0
    write('resolved-retire-cell-inputs.json', pending)
    write('corrections-draft.json', draft)
    write('physical-cell-phase-review.json', reviewed)
    write('mapped-ack-interface.json', dict(passed=True, tag=inv['tag'], variant=inv['variant'],
          valid_expression='dut.ld_rsp_valid', ready_expression='(!dut.ld_rsp_ready)', connections=ports))
    print('M3_RETIRE_PHASE_RESOLVED', len(pending), len(draft['aliases']), flush=True)


if __name__ == '__main__':
    resolve()
