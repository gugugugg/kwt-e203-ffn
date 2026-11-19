"""Resolve the new operand encoding and the actual mapped DMA ACK boundary."""
import json
from pathlib import Path
import shutil


def resolve(folder):
    def read(name):
        return json.loads((folder / name).read_text())

    def write(name, value):
        (folder / name).write_text(json.dumps(value, indent=2) + '\n')

    inventory = read('inventory.json')
    cells = inventory['cells']
    connectivity = read('connectivity.json')
    draft = read('corrections-draft.json')
    cell_review = read('physical-cell-phase-review.json')
    pending = read('phase-review-pending.json')
    inputs = {row['rtl']: row for row in read('cell-inverted-review-inputs.json')}

    def driver(net):
        segment = connectivity['representatives'].get(net, net)
        record, = connectivity['drivers'][segment]
        return dict(record, pins=cells[record['cell']]['pins'])

    expected_operands = {
        'jp_input_return[38]': 'ap_input_rdata[22]',
        'jp_input_return[24]': 'ap_input_rdata[8]',
        'operand_weight[209]': 'pm_rdata[209]',
    }
    for row in pending:
        if row['kind'] == 'cell_encoding':
            item = inputs[row['rtl']]
            pins = item['pins']
            parent = row['cell'].rsplit('/', 1)[0] + '/'
            reset = driver(parent + pins['RN'].strip())
            enable = driver(parent + pins['E'].strip())
            assert item['ref'] == 'EDGRNQNV6_12TR40' and pins['D'] == "1'b1"
            assert reset['ref'] == 'NAND2CV0_12TR40'
            assert reset['pins']['A1'] == expected_operands.pop(row['rtl'].rsplit('/', 1)[1])
            cell_review.append(dict(rtl=row['rtl'], physical_inverted=False, output='QN',
                net=item['QN_net'],
                reason='With the capture enable asserted, the literal udp_edfft samples synchronous RN. '
                       'D is tied high, RN is the NAND of positive RAM data and capture enable, '
                       'and the output inverter therefore restores the positive operand.',
                evidence=dict(cell=row['cell'], pins=pins, synchronous_reset_driver=reset,
                              enable_driver=enable)))
        else:
            output, = row['drivers']
            ff = cells[output['cell']]
            parent = output['cell'].rsplit('/', 1)[0] + '/'
            mux = driver(parent + ff['pins']['D'])
            load = driver(parent + mux['pins']['B'])
            assert ff['ref'] == 'DRNQNV4_12TR40' and output['pin'] == 'QN'
            assert mux['ref'] == 'OAI21V0_12TR40'
            assert mux['pins']['A1'] == load['pins']['A1'] == 'lden'
            assert mux['pins']['A2'] == 'qout_0__BAR'
            assert load['ref'] == 'NAND2CV0_12TR40' and load['pins']['A2'] == 'dnxt[0]'
            assert row['segment'].endswith('/i_icb_cmd_valid_BAR')
            for alias in row['aliases']:
                draft['aliases'].append(dict(rtl=alias['rtl'], gate=alias['gate'], inverted=True,
                    reason='The actual OAI21/NAND feedback cone stores positive dnxt[0] when enabled '
                           'and retains the positive internal Q. The library QN port is negative.',
                    evidence=dict(ff=ff, driver=output, feedback_mux=mux, load_cone=load)))
    assert not expected_operands
    write('resolved-r3o-phase-inputs.json', pending)
    write('physical-cell-phase-review.json', cell_review)
    draft['pending'] = 0
    write('corrections-draft.json', draft)

    engine = next(path for path in cells if path.endswith('/dma_frontend/loading_dma'))
    arbiter = 'shared_memory/memory_arbiter'
    interface = {}
    for field in ('valid', 'ready'):
        signal = 'ld_rsp_' + field
        assert cells['shared_memory']['pins'][signal].strip() == cells['soc']['pins'][signal].strip() == signal
        assert cells[arbiter]['pins']['b_rsp_' + field].strip() == signal
        inner = engine.rsplit('/', 1)[0] + '/' + cells[engine]['pins']['mem_rsp_' + field].strip()
        reps = connectivity['representatives']
        assert reps.get(inner, inner) == reps.get(signal, signal)
        interface[field] = {'signal': signal, 'engine_pin': engine + '/mem_rsp_' + field,
                            'arbiter_pin': arbiter + '/b_rsp_' + field}
    write('mapped-ack-interface.json', dict(passed=True, tag=inventory['tag'], variant=inventory['variant'],
          valid_expression='dut.ld_rsp_valid', ready_expression='dut.ld_rsp_ready', connections=interface))


def reconcile(folder, verdict):
    def read(name):
        return json.loads((folder / name).read_text())

    draft = read('corrections-draft.json')
    connectivity = read('connectivity.json')
    cells = read('inventory.json')['cells']
    expectations = read('phase-expectations.json')['nets']
    snapshot = folder / 'analysis-recovery/probe-attempt-01'
    snapshot.mkdir(parents=True, exist_ok=True)
    for name in ('corrections-draft.json', 'phase-expectations.json'):
        shutil.copyfile(folder / name, snapshot / name)
    shutil.copyfile(verdict, snapshot / 'comparison-verdict.json')
    records = {}
    for mismatch in json.loads(verdict.read_text())['mismatches']:
        net = mismatch['net']
        segment = connectivity['representatives'].get(net, net)
        if segment in records:
            continue
        source = expectations[net]['sources']
        driver, = connectivity['drivers'][segment]
        cell = cells[driver['cell']]
        negative = {row['rtl'] for row in source if row['inverted']}
        duplicates = set()
        if '/jtag_' in segment or '/aonrst_catch/' in segment:
            assert cell['ref'] == 'CLKMUX2V12_12TR40' and cell['pins']['Z'] == 'io_sync_reset'
            assert all(rtl.endswith('/rst_n') for rtl in negative)
            reason = 'Reset catcher is the active-high driver. Suppress active-low consumer aliases.'
        elif segment.endswith('/memory/we_BAR') and '/u_e203_dtcm_ram/' in segment:
            assert cell['ref'] == 'OAI21V2_12TR40' and cell['pins']['ZN'] == 'o_dat[55]'
            assert any(row['rtl'].endswith('/o_dat[55]') and not row['inverted'] for row in source)
            duplicates = {row['rtl'] for row in source if row['rtl'].endswith('/uop_cmd_read')}
            reason = 'Native driver is the command read bit o_dat[55]. RTL ram_we is its complement.'
        else:
            assert segment.endswith('/cmt_dpc_ena')
            assert cell['ref'] == 'CLKINV2_12TR40' and cell['pins'] == dict(I='step_req_nxt', ZN='cmt_dpc_ena')
            assert all(rtl.endswith('/step_req_dfflr/dnxt[0]') for rtl in negative)
            reason = 'Keep positive cmt_dpc_ena from its physical producer. The step-request D alias is opposite.'
        records[segment] = dict(driver=driver, pins=cell['pins'], reason=reason,
                                suppressed=sorted(negative), deduplicated=sorted(duplicates))
    draft['suppressed_opposite_phase_aliases'] = sorted(
        {rtl for row in records.values() for rtl in row['suppressed']})
    draft['deduplicated_positive_aliases'] = sorted(
        {rtl for row in records.values() for rtl in row['deduplicated']})
    for name, value in [('corrections-draft.json', draft), ('probe01-physical-source-review.json', records)]:
        (folder / name).write_text(json.dumps(value, indent=2) + '\n')


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3:
        reconcile(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        resolve(Path(sys.argv[1]))
