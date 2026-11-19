"""Reconcile probe-one alias overwrites against the actual final driver pins."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from assemble_ffn_ar_area_review import assemble
from ffn_ar_area import REPORT, dump


def read(path):
    return json.loads(path.read_text())


def reconcile(name):
    folder = REPORT / 'activity-mapping/native-review-first' / name
    draft = read(folder / 'corrections-draft.json')
    conn = read(folder / 'connectivity.json')
    inv = read(folder / 'inventory.json')
    verdict = read(folder / 'probe-attempt-01/comparison-verdict.json')
    before = folder / 'analysis-recovery/probe01-source-overwrite'
    for source in [folder / 'corrections-draft.json', folder / 'phase-expectations.json',
                   *sorted((folder / 'reviewed-draft').glob('*'))]:
        target = before / source.relative_to(folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source), str(target))
    groups = {conn['representatives'].get(e['net'], e['net']): e for e in verdict['errors']}
    opposite = set(draft['suppressed_opposite_phase_aliases'])
    duplicates = set(draft.get('deduplicated_positive_aliases', []))
    reviewed = []
    for key, error in groups.items():
        sources = error['sources']
        negative = {s['rtl'] for s in sources if s['inverted']}
        positive = {s['rtl'] for s in sources if not s['inverted']}
        driver, = conn['drivers'][key]
        cell = inv['cells'][driver['cell']]
        drop = set()
        dedup = set()
        retarget = None
        if '/jtag_' in key and key.endswith('/rst_n_BAR'):
            assert cell['ref'] == 'CLKMUX2V12_12TR40' and cell['pins']['Z'] == 'io_sync_reset'
            drop = negative
            reason = 'JTAG reset catcher mux drives active-high io_sync_reset; active-low CDC reset aliases overwrite the shared segment.'
        elif '/aonrst_catch/io_sync_reset' in key:
            assert cell['ref'] == 'CLKMUX2V12_12TR40' and cell['pins']['Z'] == 'io_sync_reset'
            drop = negative
            reason = 'AON reset catcher mux drives active-high io_sync_reset; drop the lclkgen reset-low aliases on its output.'
        elif key.endswith('/we_BAR') and '/u_e203_dtcm_ram/' in key:
            assert cell['pins'][driver['pin']] == 'o_dat[55]'
            assert any(s.endswith('/o_dat[55]') for s in positive)
            drop = negative
            dedup = {s for s in positive if s.endswith('/uop_cmd_read')}
            reason = 'DTCM read field o_dat[55] is the physical producer; ram_we is the complement. Keep the upstream read representation.'
        elif key.endswith('/alu_wbck_i_ready_BAR'):
            assert cell['ref'] == 'AND3V0_12TR40' and cell['pins']['Z'].strip() == 'longp_wbck_o_valid'
            drop = negative
            dedup = {s for s in positive if s.endswith('/longp_wbck_i_valid')}
            reason = 'AND3 output is the long-pipe valid producer; ALU ready is its complement.'
        elif key.endswith('/cmt_dpc_ena_BAR'):
            assert cell['ref'] == 'CLKNAND2V8_12TR40' and any('/step_req_dfflr/dnxt[0]' in s for s in positive)
            drop = negative
            reason = 'step_req_nxt equals !cmt_dpc_ena by absorption; retain the physical step-request source at the NAND output.'
        elif key.endswith('/cmt_dpc_ena'):
            assert cell['ref'] == 'CLKINV2_12TR40' and cell['pins']['I'] == 'step_req_nxt'
            rtl, = negative
            retarget = (rtl, conn['pins'][driver['cell'] + '/I'])
            reason = 'Drive step_req_nxt from its matching RTL source at the inverter input and retain native cmt_dpc_ena aliases at the output.'
        elif key.endswith('/b_cmd_read'):
            assert cell['ref'] == 'INV2SR_12TR40' and cell['pins'] == dict(I='pio_cmd_read', ZN='mem_cmd_read')
            drop = negative
            reason = 'The inverter output is mem_cmd_read=!output_transfer. Remove opposite PIO direction aliases on the memory segment.'
        elif key.endswith('/i_icb_cmd_valid_BAR'):
            assert cell['ref'] == 'CLKINV0_12TR40' and cell['pins'] == dict(I='qout_0_', ZN='qout_0__BAR')
            rtl, = [s for s in negative if s.endswith('/qout[0]')]
            retarget = (rtl, conn['pins'][driver['cell'] + '/I'])
            drop = negative - {rtl}
            reason = 'Map the original valid FF directly to physical positive Q; derive the negative splitter branch through the actual inverter.'
        else:
            raise RuntimeError(key)
        if retarget:
            rtl, gate = retarget
            rule, = [row for row in draft['aliases'] if row['rtl'] == rtl]
            rule.pop('gate_pin', None)
            rule.update(gate=gate, inverted=False, reason=reason)
        opposite.update(drop)
        duplicates.update(dedup)
        reviewed.append(dict(segment=key, driver=driver, pins=cell['pins'], reason=reason,
                             suppressed=sorted(drop), deduplicated=sorted(dedup), retarget=retarget))
    draft.update(suppressed_opposite_phase_aliases=sorted(opposite),
                 deduplicated_positive_aliases=sorted(duplicates))
    dump(folder / 'corrections-draft.json', draft)
    dump(folder / 'probe01-physical-source-review.json',
         dict(variant=name, tag=inv['tag'], segments=reviewed, original_map_and_SAIF_unchanged=True))
    assemble(name)
    collisions = read(folder / 'corrected-injection-collisions.json')
    dump(folder / 'injection-source-ambiguities.json',
         dict(audited_ambiguous_groups=[], unknown_alias_groups=collisions, original_SAIF_unchanged=True))


if __name__ == '__main__':
    for variant in ('ffn_ara_SS', 'ffn_ara_SR'):
        reconcile(variant)
