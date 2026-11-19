"""Keep one literal producer on each measured mixed-polarity segment."""
from pathlib import Path
import shutil

from phase import REPORT, REVIEW
from resolve_phase import read, write


def main():
    conn, inv = read('connectivity.json'), read('inventory.json')
    original = read('corrections-draft.json')
    expectations = read('phase-expectations.json')['nets']
    import json
    verdict = json.loads((REPORT / 'phase-verdict.json').read_text())
    assert verdict['attempt'] == 'probe-attempt-01' and not verdict['passed']
    backup = REVIEW / 'analysis-recovery' / verdict['attempt']
    backup.mkdir(parents=True)
    shutil.copyfile(REPORT / 'phase-verdict.json', backup / 'comparison-verdict.json')
    for name in ('corrections-draft.json', 'phase-expectations.json'):
        shutil.copyfile(REVIEW / name, backup / name)
    shutil.copytree(REVIEW / 'reviewed-draft', backup / 'reviewed-draft')

    segments = {}
    for row in verdict['mismatches']:
        net = row['net']
        segments[conn['representatives'].get(net, net)] = expectations[net]['sources']
    assert len(segments) == 5
    suppressed = set(original['suppressed_opposite_phase_aliases'])
    duplicates = set(original.get('deduplicated_positive_aliases', []))
    evidence = {}
    for segment, sources in segments.items():
        driver, = conn['drivers'][segment]
        pins = {name: value.strip() for name, value in inv['cells'][driver['cell']]['pins'].items()}
        if driver['ref'] == 'CLKMUX2V12_12TR40' and pins['Z'] == 'io_sync_reset':
            suffix = '/io_sync_reset'
            reason = 'The native reset catcher drives active-high io_sync_reset. Consumer rst_n aliases describe the inverse.'
        elif driver['ref'] == 'NAND2CV8_12TR40' and pins['ZN'] == 'cmt_dpc_ena_BAR':
            suffix = '/step_req_dfflr/dnxt[0]'
            reason = 'The actual NAND drives inverted debug-entry enable and the positive step-request input. That input is the direct physical source for the frozen RTL.'
        elif driver['ref'] == 'BUFV16RD_12TR40' and pins['Z'] == 'o_dat[55]':
            suffix = '/u_byp_icb_cmd_buf/o_dat[55]'
            reason = 'The command-buffer read bit drives the actual active-low SRAM write input; RTL ram_we is the inverse of uop_cmd_read.'
        elif driver['ref'] == 'INV2SR_12TR40' and pins == dict(I='pio_cmd_read', ZN='mem_cmd_read'):
            suffix = '/loading_dma/mem_cmd_read'
            reason = 'The actual INV derives the memory direction from the opposite PIO direction. Retain the direct memory command source.'
        else:
            raise RuntimeError('Review unknown mixed segment: ' + segment)
        producer, = [row for row in sources if row['rtl'].endswith(suffix)]
        assert not producer['inverted']
        opposite = [r['rtl'] for r in sources if r['rtl'] != producer['rtl'] and r['inverted']]
        redundant = [r['rtl'] for r in sources if r['rtl'] != producer['rtl'] and not r['inverted']]
        suppressed.update(opposite)
        duplicates.update(redundant)
        evidence[segment] = dict(driver=driver, pins=pins, reason=reason,
                                 producer=producer, suppressed=opposite, deduplicated=redundant)
    original['suppressed_opposite_phase_aliases'] = sorted(suppressed)
    original['deduplicated_positive_aliases'] = sorted(duplicates)
    write('corrections-draft.json', original)
    write('probe01-physical-source-review.json', evidence)
    print('M3_RETIRE_SOURCE_REVIEW', len(segments), len(suppressed), len(duplicates), flush=True)


if __name__ == '__main__':
    main()
