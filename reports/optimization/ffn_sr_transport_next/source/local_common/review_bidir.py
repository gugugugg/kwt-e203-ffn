"""Resolve the transport candidate's actual final cell and control phases."""
from itertools import product
import json
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sr_area.check_mapped_ack import PRIMITIVE, evaluate_gate


def resolve(folder):
    def read(name):
        return json.loads((folder / name).read_text())

    def write(name, data):
        (folder / name).write_text(json.dumps(data, indent=2) + '\n')

    inventory = read('inventory.json')
    cells = inventory['cells']
    connectivity = read('connectivity.json')
    draft = read('corrections-draft.json')
    reviews = read('physical-cell-phase-review.json')
    pending = read('phase-review-pending.json')
    encoded = {row['rtl']: row for row in read('cell-inverted-review-inputs.json')}
    reps = connectivity['representatives']
    library = (folder / 'vendor-functions.v').read_text()
    models = {m[1]: m[2].split('specify')[0]
              for m in re.finditer(r'module\s+(\w+)\b(.*?)endmodule', library, re.S)}

    def driver(net):
        row, = connectivity['drivers'][reps.get(net, net)]
        return dict(row, pins=cells[row['cell']]['pins'])

    def negative_alias(row, reason, evidence):
        draft['aliases'].append(dict(rtl=row['rtl'], gate=row['gate'], inverted=True,
                                     reason=reason, evidence=evidence))

    for row in pending:
        if row['kind'] == 'cell_encoding':
            original = encoded[row['rtl']]
            top = row['cell'].rsplit('/', 1)[0] + '/'
            pins = original['pins']
            load = driver(top + pins['D'])
            bit = re.search(r'\[(\d+)\]$', row['rtl'])[1]
            if row['ref'] == 'EDQNV6_12TR40':
                assert load['ref'].startswith('CLKINV') and load['pins']['I'] == 'dnxt[' + bit + ']'
                assert pins['E'] == 'lden' and pins['QN'].strip() == 'qout[' + bit + ']'
                reason = 'The literal inverter on dnxt and the library QN inverter cancel.'
                output, phase, path = 'QN', False, [load]
            else:
                assert row['ref'] == 'DQV8_12TR40' and load['ref'].startswith('CLKMUX2')
                assert load['pins']['I0'] == pins['Q'] and load['pins']['S'] == 'lden'
                invert = driver(top + load['pins']['I1'])
                assert invert['ref'].startswith('CLKINV') and invert['pins']['I'] == 'dnxt[' + bit + ']'
                reason = 'The enable mux loads inverted dnxt and retains Q in the hold branch.'
                output, phase, path = 'Q', True, [load, invert]
            net = original[output + '_net']
            evidence = dict(cell=row['cell'], pins=pins, input_cone=path)
            reviews.append(dict(rtl=row['rtl'], physical_inverted=phase, output=output, net=net,
                                reason=reason, evidence=evidence))
            if phase:
                draft['replace_native_cell_aliases'].append(row['rtl'])
                negative_alias(dict(rtl=row['rtl'], gate=net), reason, evidence)
        elif row['segment'].endswith('/dec_bxx_BAR'):
            root = driver(row['segment'])
            scope = root['cell'].rsplit('/', 1)[0] + '/'
            checked = {}

            def value(net, inputs):
                if net in inputs:
                    return inputs[net]
                gate = driver(scope + net)
                assert gate['cell'].startswith(scope)
                checked[gate['cell']] = gate
                local = {}
                for op, raw in PRIMITIVE.findall(models[gate['ref']]):
                    output, *signals = (s.strip() for s in raw.split(','))
                    local[output] = evaluate_gate(op, [
                        local[s] if s in local else value(gate['pins'][s].strip(), inputs)
                        for s in signals])
                return local[gate['pin']]

            bits = list(range(7)) + [14, 15]
            for values in product((False, True), repeat=len(bits)):
                instr = sum(int(bit) << index for index, bit in zip(bits, values))
                branch = (instr & 127) == 0x63 or ((instr & 3) == 1 and (instr >> 14) == 3)
                inputs = {'i_instr[%d]' % index: bit for index, bit in zip(bits, values)}
                assert value('dec_bxx_BAR', inputs) == (not branch)
            for alias in row['aliases']:
                negative_alias(alias, 'Literal decoder cone is the complement of the original 32-bit '
                               'and compressed branch decodes.', dict(gates=checked, combinations=512))
        else:
            assert row['segment'].endswith('/pc_dfflr/lden_BAR')
            base = row['segment'].rsplit('/', 1)[0] + '/'
            inversion = cells[base + 'U2']
            mux = cells[base + 'U5']
            load = cells[base + 'U4']
            assert inversion['pins'] == dict(I='lden_BAR', ZN='n36')
            assert mux['ref'].startswith('OAI21') and mux['pins']['A1'] == 'n36'
            assert load['ref'].startswith('NAND2') and load['pins'] == dict(A1='n36', A2='dnxt[1]', ZN=mux['pins']['B'])
            for alias in row['aliases']:
                negative_alias(alias, 'The literal PC register load mux uses the inverted lden_BAR.',
                               dict(driver=driver(row['segment']), inversion=inversion, load=load, mux=mux))
    for row in read('bar-segment-review-inputs.json'):
        if '/u_e203_subsys_plic/' not in row['segment'] or not row['segment'].endswith('/rst_n'):
            continue
        output = driver(row['segment'])
        scope = output['cell'].rsplit('/', 1)[0] + '/'
        preceding = driver(scope + output['pins']['I'])
        assert output['ref'].startswith('CLKINV') and preceding['ref'].startswith('CLKINV')
        assert preceding['pins']['I'] == 'rst_n'
        names = {alias['rtl'] for alias in row['aliases']}
        for alias in draft['aliases']:
            if alias['rtl'] in names:
                alias.update(inverted=alias['rtl'].endswith('/reset'),
                             reason='Two literal inverters restore active-low PLIC rst_n. '
                                    'The gateway active-high reset is its complement.',
                             evidence=dict(preceding=preceding, output=output))
    draft['pending'] = 0
    write('resolved-bidir-phase-inputs.json', pending)
    write('physical-cell-phase-review.json', reviews)
    write('corrections-draft.json', draft)

    engine = next(path for path in cells if path.endswith('/dma_frontend/loading_dma'))
    arbiter = 'shared_memory/memory_arbiter'
    links = {}
    for field in ('valid', 'ready'):
        signal = 'ld_rsp_' + field
        assert cells['shared_memory']['pins'][signal].strip() == cells['soc']['pins'][signal].strip() == signal
        assert cells[arbiter]['pins']['b_rsp_' + field].strip() == signal
        inner = engine.rsplit('/', 1)[0] + '/' + cells[engine]['pins']['mem_rsp_' + field].strip()
        assert reps.get(inner, inner) == reps.get(signal, signal)
        links[field] = dict(shared_pin=arbiter + '/b_rsp_' + field, engine_pin=engine + '/mem_rsp_' + field)
    write('mapped-ack-interface.json', dict(passed=True, tag=inventory['tag'], variant=inventory['variant'],
          valid_expression='dut.ld_rsp_valid', ready_expression='dut.ld_rsp_ready', connections=links))


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
    decisions = {}
    for mismatch in json.loads(verdict.read_text())['mismatches']:
        net = mismatch['net']
        segment = connectivity['representatives'].get(net, net)
        if segment in decisions:
            continue
        sources = expectations[net]['sources']
        driver, = connectivity['drivers'][segment]
        cell = cells[driver['cell']]
        negative = {row['rtl'] for row in sources if row['inverted']}
        duplicates = set()
        if '/jtag_' in segment or '/aonrst_catch/' in segment:
            assert cell['ref'] == 'CLKMUX2V12_12TR40' and cell['pins']['Z'] == 'io_sync_reset'
            reason = 'Preserve the active-high reset-catcher output over the active-low aliases.'
        elif segment.endswith('/memory/we_BAR') and '/u_e203_dtcm_ram/' in segment:
            assert cell['ref'] == 'INV5SR_12TR40' and cell['pins']['ZN'] == 'o_dat[55]'
            assert any(row['rtl'].endswith('/o_dat[55]') and not row['inverted'] for row in sources)
            duplicates = {row['rtl'] for row in sources if row['rtl'].endswith('/uop_cmd_read')}
            reason = 'Preserve o_dat[55] as the native read bit, complementary to ram_we.'
        elif segment.endswith('/i_icb_cmd_valid_BAR'):
            assert cell['ref'] == 'CLKINV0_12TR40'
            assert cell['pins'] == dict(I='qout_0_', ZN='qout_0__BAR')
            assert any(row['rtl'].endswith('/i_rdy') and not row['inverted'] for row in sources)
            reason = 'Preserve positive FIFO-ready aliases on the physical inverted FIFO valid output.'
        elif segment == 'shared_memory/memory_arbiter/b_cmd_read':
            assert cell['ref'] == 'INV2SR_12TR40'
            assert cell['pins'] == dict(I='pio_cmd_read', ZN='mem_cmd_read')
            reason = 'The shared interface carries mem_cmd_read, physically inverted from PIO read.'
        else:
            assert segment.endswith('/icb2mem_dfflr/dnxt[0]')
            assert cell['ref'] == 'CLKINV0_12TR40' and cell['pins'] == dict(I='n512', ZN='n513')
            assert all(rtl.endswith('/icb2itcm_dfflr/dnxt[0]') for rtl in negative)
            reason = 'Preserve the native BIU-select register input over the complementary ITCM-select alias.'
        decisions[segment] = dict(driver=driver, pins=cell['pins'], reason=reason,
                                  suppressed=sorted(negative), deduplicated=sorted(duplicates))
    draft['suppressed_opposite_phase_aliases'] = sorted(
        {rtl for row in decisions.values() for rtl in row['suppressed']})
    draft['deduplicated_positive_aliases'] = sorted(
        {rtl for row in decisions.values() for rtl in row['deduplicated']})
    for name, value in [('corrections-draft.json', draft), ('probe01-physical-source-review.json', decisions)]:
        (folder / name).write_text(json.dumps(value, indent=2) + '\n')


if __name__ == '__main__':
    if len(sys.argv) == 3:
        reconcile(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        resolve(Path(sys.argv[1]))
