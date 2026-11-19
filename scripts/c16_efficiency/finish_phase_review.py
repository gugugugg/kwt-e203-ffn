"""Resolve this W final's own positive encoded branches and opposite aliases."""
import json
from pathlib import Path
from prepare import REPORT


def main():
    out=REPORT/'activity-mapping/native-review-W/ffn_ce_W'
    draft=json.loads((out/'corrections-draft.json').read_text())
    conn=json.loads((out/'connectivity.json').read_text())
    inv=json.loads((out/'inventory.json').read_text())
    activity=json.loads((out/'saif-index.json').read_text())['activity']
    groups=json.loads((out/'bar-segment-review-inputs.json').read_text())
    aliases={r['rtl']:r for r in draft['aliases']}
    suppressed=set(draft.get('suppressed_opposite_phase_aliases',[]))
    notes=[]
    for group in groups:
        key=group['segment'];rows=group['aliases']
        if '/jtag_' in key and key.endswith('/rst_n_BAR'):
            for row in rows:
                if not row['rtl'].endswith('/jtag_TRST'):
                    suppressed.add(row['rtl']);aliases.pop(row['rtl'],None)
            notes.append(dict(segment=key,physical_phase='positive jtag_TRST/reset catch output',
                evidence='Actual ResetCatchAndSync CLKMUX Z is active-high reset; preserve direct jtag_TRST, suppress complementary CDC rst_n mappings'))
        elif '/aonrst_catch/io_sync_reset' in key:
            for row in rows:
                suppressed.add(row['rtl']);aliases.pop(row['rtl'],None)
            if key not in activity:raise RuntimeError('Read the actual positive AON reset source')
            aliases[key]=dict(rtl=key,gate=key,inverted=False,
                reason='Own ResetCatchAndSync positive io_sync_reset directly drives actual CLKMUX Z.',evidence=group['drivers'])
            notes.append(dict(segment=key,physical_phase='positive io_sync_reset',
                evidence='Use actual same-name SAIF reset-catch output; only the two complementary lclkgen rst_n aliases are suppressed'))
        elif '/o_axi_aw_fifo/' in key:
            for row in rows:
                if '/qout[' not in row['rtl']:
                    suppressed.add(row['rtl']);aliases.pop(row['rtl'],None)
            notes.append(dict(segment=key,physical_phase='positive actual FIFO full Q',
                evidence='Literal DRNQ output is original positive qout[1]; AXI ready/i_rdy are logical complements and are suppressed'))
        elif '/u_sirv_plic_man/' in key and key.endswith('/rst_n'):
            base=key.split('/u_sirv_plic_man/')[0]+'/u_sirv_plic_man/'
            a=inv['cells'][base+'U463'];b=inv['cells'][base+'U8']
            if a['pins']!={'I':'rst_n','ZN':'n363'} or b['pins']!={'I':'n363','ZN':'n346'}:
                raise RuntimeError('Inspect this own PLIC reset chain')
            for row in rows:
                aliases.pop(row['rtl'],None)
                if row['rtl'].endswith('/reset'):suppressed.add(row['rtl'])
            notes.append(dict(segment=key,physical_phase='positive rst_n',
                evidence='Actual U463 CLKINV12 rst_n->n363 then U8 CLKINV12 n363->n346; retain original positive rst_n aliases, suppress only opposite active-high LevelGateway.reset sources'))
        elif '/u_e203_itcm_ctrl/' in key and key.endswith('/qout[0]'):
            for row in rows:
                if row['rtl'].endswith('/qout[0]'):
                    aliases[row['rtl']]=dict(rtl=row['rtl'],gate=row['gate'],inverted=False,
                        reason='Own reset-zero generic qout is exposed positive after actual DRNQN inverted QN followed by U2 CLKINV2.',evidence=group['drivers'])
                else:
                    suppressed.add(row['rtl']);aliases.pop(row['rtl'],None)
            notes.append(dict(segment=key,physical_phase='positive qout[0]',
                evidence='Own DRNQNV4 negative QN n7 followed by U2 CLKINV2; o_vld and qout are positive, readiness aliases are complements'))
    draft['aliases']=list(aliases.values())
    draft['suppressed_opposite_phase_aliases']=sorted(suppressed)
    draft['primary_mixed_branch_notes']=notes
    (out/'corrections-draft.json').write_text(json.dumps(draft,indent=2))
    (out/'primary-positive-branch-review.json').write_text(json.dumps(notes,indent=2))
    print('EFFICIENCY_PRIMARY_PHASE_RESOLUTION',len(aliases),len(suppressed),flush=True)


if __name__=='__main__':main()
