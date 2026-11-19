"""Retain one literal producer for each measured ambiguous physical segment."""
import json
import re
import shutil
import sys

from phase_overlap import ROOT, bind, phase


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def select(mode, native=False, variant=None):
    name, report, _, review = bind(mode, native=native, variant=variant)
    choice_path = review / 'probe01-source-review.json'
    backup = review / 'analysis-recovery/probe-attempt-01'
    backup.mkdir(parents=True)
    for filename in ('corrections-draft.json', 'phase-expectations.json'):
        shutil.copyfile(review / filename, backup / filename)
    shutil.copytree(review / 'reviewed-draft', backup / 'reviewed-draft')

    inv, conn = (read(review / filename) for filename in ('inventory.json', 'connectivity.json'))
    draft = read(review / 'corrections-draft.json')
    expectations = read(review / 'phase-expectations.json')['nets']
    reps = conn['representatives']
    cells = inv['cells']
    if native:
        choices = read(choice_path)
    else:
        verdict = read(report / 'phase-verdict.json')
        representatives = {}
        for row in verdict['mismatches']:
            representatives.setdefault(reps.get(row['net'], row['net']), row['net'])
        choices = []
        for representative, net in representatives.items():
            driver, = conn['drivers'][representative]
            cell = driver['cell']
            ref = driver['ref']
            pins = {p: v.strip() for p, v in cells[cell]['pins'].items()}
            negative = False
            if ref == 'CLKMUX2V12_12TR40' and pins['Z'] == 'io_sync_reset':
                suffix = '/io_sync_reset'
                reason = 'The literal reset-catcher output is the common active-high producer.'
            elif ref in ('CLKNAND2V8_12TR40','NAND2V2_12TR40') and pins['ZN'] == 'cmt_dpc_ena_BAR':
                suffix = '/step_req_dfflr/dnxt[0]'
                reason = 'The NAND produces the complement of cmt_dpc_ena. The RTL step_req_nxt reduces to that complement because step_req_set includes !dbg_entry_taken_ena.'
            elif pins.get(driver['pin']) == 'o_dat[55]' and cell.rsplit('/', 1)[0].endswith('/u_byp_icb_cmd_buf'):
                model = (review / 'vendor-functions.v').read_text()
                route, inversions = [], 0
                root = driver
                while 'I' in cells[root['cell']]['pins'] and root['pin'] in ('Z', 'ZN'):
                    output = root['pin']
                    operation = 'not' if output == 'ZN' else 'buf'
                    definition = re.search(r'\bmodule\s+'+root['ref']+r'\b[\s\S]*?endmodule', model)[0]
                    assert re.search(r'\b'+operation+r'\s+\w+\s*\(\s*'+output+r'\s*,\s*I\s*\)', definition)
                    route.append(dict(root, pins=cells[root['cell']]['pins']))
                    inversions += output == 'ZN'
                    source = conn['pins'][root['cell']+'/I']
                    upstream = conn['drivers'].get(reps.get(source, source), [])
                    if len(upstream) != 1:
                        break
                    root, = upstream
                assert route and inversions % 2 == 0
                sram_ctrl = ROOT / 'build/server/official_2025/e203_hbirdv2-master/rtl/e203/general/sirv_1cyc_sram_ctrl.v'
                assert 'ram_we = (~uop_cmd_read)' in sram_ctrl.read_text()
                suffix = '/u_byp_icb_cmd_buf/o_dat[55]'
                reason = 'The actual producer is command-buffer read bit 55. The original DTCM controller assigns ram_we = !uop_cmd_read.'
            elif ref in ('CLKINV0_12TR40', 'INV0_12TR40') and pins == dict(I='qout_0_', ZN='qout_0__BAR'):
                parent = cell.rsplit('/', 1)[0]
                state, = conn['drivers'][conn['pins'][cell + '/I']]
                assert state['cell'] == parent + '/qout_r_reg_0_' and state['ref'] in ('DRNQV0_12TR40', 'DRNQV6_12TR40')
                reg = {p: v.strip() for p, v in cells[state['cell']]['pins'].items()}
                assert reg['RDN'] == 'rst_n' and reg['Q'] == 'qout_0_'
                feedback, = conn['drivers'][conn['pins'][state['cell'] + '/D']]
                feedback_pins = {p: v.strip() for p, v in cells[feedback['cell']]['pins'].items()}
                assert feedback['ref'] == 'OAI21V0_12TR40' and feedback_pins['A1'] == 'lden' and feedback_pins['A2'] == 'qout_0__BAR'
                capture, = conn['drivers'][conn['pins'][feedback['cell'] + '/B']]
                cp = {p: v.strip() for p, v in cells[capture['cell']]['pins'].items()}
                assert capture['ref'] == 'NAND2CV0_12TR40' and {cp['A1'], cp['A2']} == {'lden', 'dnxt[0]'}
                if parent.endswith('/ir_valid_dfflr'):
                    ifetch = ROOT / 'build/server/official_2025/e203_hbirdv2-master/rtl/e203/core/e203_ifu_ifetch.v'
                    text = ifetch.read_text()
                    assert 'ir_valid_dfflr (ir_valid_ena, ir_valid_nxt, ir_valid_r, clk, rst_n)' in text
                    assert 'ifu_o_valid  = ir_valid_r' in text
                    suffix = '/ir_valid_dfflr/qout[0]'
                else:
                    suffix = '/dp_gt0.vec_31_dfflr/qout[0]'
                negative = True
                reason = 'The reset-zero Q stores dnxt on lden and holds on !lden. The observed inverter is the complement of the positive FIFO vector bit. Its corresponding RTL valid and opposite ready aliases share the segment.'
            else:
                raise ValueError((net, driver, pins))
            candidates = expectations[net]['sources']
            producer, = [row for row in candidates if row['rtl'].endswith(suffix) and row['inverted'] == negative]
            choices.append(dict(net=net, driver=driver, pins=pins, producer=producer['rtl'],
                                inverted=negative, reason=reason,
                                alternatives=[row for row in candidates if row is not producer]))
            if suffix == '/u_byp_icb_cmd_buf/o_dat[55]':
                choices[-1]['physical_route'] = route
        write(choice_path, choices)

    opposite, duplicates = set(), set()
    for row in choices:
        driver, = conn['drivers'][reps.get(row['net'], row['net'])]
        assert driver == row['driver']
        assert row['pins'] == {p: v.strip() for p, v in cells[driver['cell']]['pins'].items()}
        expected = expectations[row['net']]['sources']
        assert any(s['rtl'] == row['producer'] and s['inverted'] == row['inverted'] for s in expected)
        others = [s for s in expected if s['rtl'] != row['producer']]
        assert sorted(s['rtl'] for s in others) == sorted(s['rtl'] for s in row['alternatives'])
        opposite.update(s['rtl'] for s in others if s['inverted'] != row['inverted'])
        duplicates.update(s['rtl'] for s in others if s['inverted'] == row['inverted'])
    draft['suppressed_opposite_phase_aliases'] = sorted(opposite)
    draft['deduplicated_positive_aliases'] = sorted(duplicates)
    write(review / 'corrections-draft.json', draft)
    if not native:
        shutil.copyfile(report / 'phase-verdict.json', report / 'phase-probe01-verdict.json')
    phase.local_review('assemble')
    print('BANK_CANONICAL_PHASE_PRODUCERS', name, len(choices), len(opposite), len(duplicates))


if __name__ == '__main__':
    select(sys.argv[1], native=sys.argv[2:] == ['--native'])
