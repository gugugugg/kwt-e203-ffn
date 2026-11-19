"""Keep the direct physical expression when opposite semantic aliases collide in PT."""
import json,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'scripts/c_final_energy')]
from ffn_c_final_energy import REPORT,dump
from assemble_ffn_c_final_energy_review import assemble

def main():
    base=REPORT/'activity-mapping/native-review-first'
    for name in ['ffn_cfe_SS','ffn_cfe_O1']:
        p=base/name;inv=json.loads((p/'inventory.json').read_text());conn=json.loads((p/'connectivity.json').read_text());draft=json.loads((p/'corrections-draft.json').read_text())
        before=p/'query-recovery/opposite-semantic-aliases';before.mkdir(parents=True,exist_ok=True)
        for leaf in ['corrections-draft.json','phase-expectations.json','injection-source-ambiguities.json']:
            dest=before/leaf
            if not dest.exists():shutil.copyfile(str(p/leaf),str(dest))
        selected=[];evidence=[]
        for row in draft['aliases']:
            rtl=row['rtl'];reason=None
            if '/jtag_dtm_gen.u_sirv_jtag_dtm/' in rtl and rtl.endswith('/rst_n'):
                reason='Original CDC rst_n is !jtag_TRST, while actual CLKMUX Z is positive jtag_TRST/io_sync_reset. Keep the direct positive driver expression and block only this opposite reset-low alias.'
            elif '/u_aon_lclkgen_regs/' in rtl and rtl.endswith('/rst_n'):
                reason='Original lclkgen reset-low is the complement of actual aonrst_catch CLKMUX positive io_sync_reset. Keep the direct active-high reset source.'
            elif '/u_e203_cpu_top/' in rtl and (rtl.endswith('/dtcm_ram_we') or rtl.endswith('/ram_we') or '/u_e203_dtcm_ram/' in rtl and rtl.endswith(('/we','/WE'))):
                reason='Original sirv_1cyc_sram_ctrl ram_we=!uop_cmd_read. Actual BUFV/CLKBUF chain carries positive buffered o_dat[55]=uop_cmd_read to this negative-WE segment. Retain the direct positive read source, suppress opposite write aliases.'
            elif name.endswith('O1') and '/u_e203_biu/' in rtl and rtl.endswith(('/o_icb_cmd_valid','/o_vld','/qout[0]','/i_icb_cmd_valid')):
                reason='Actual positive DRNQ FIFO vec state passes through CLKINV0 to negative-valid segment. Original i_rdy=!vec_r[1] already records that direct physical polarity; retain it and suppress opposite positive-valid aliases, including their one-time-unit source representation difference.'
            if reason and row['inverted']:
                selected.append(rtl);evidence.append(dict(rtl=rtl,gate=row['gate'],reason=reason))
        assert len(selected)==(26 if name.endswith('SS') else 30),len(selected)
        draft['suppressed_opposite_phase_aliases']=selected
        dump(p/'corrections-draft.json',draft);dump(p/'opposite-semantic-alias-review.json',dict(passed=True,variant=name,tag=inv['tag'],suppressed=evidence,original_map_and_SAIF_unchanged=True,manual_activity_values_added=False,reason='Native read-SAIF-only attempt01 exposes opposite-source overwrite; retain the direct physical RTL expression determined by actual driver/port functions.'))
        assemble(name)
        collisions=json.loads((p/'corrected-injection-collisions.json').read_text());unknown=[]
        for g in collisions:
            assert any('r_gpio_sync1[' in s['rtl'] and s['raw']['T0']+s['raw']['T1']==0 for s in g['sources'])
            unknown.append(dict(segment=g['segment'],sources=g['sources'],reason='Original GPIO unknown retained alongside measured interface aliases.'))
        dump(p/'injection-source-ambiguities.json',dict(unknown_alias_groups=unknown,audited_ambiguous_groups=[],original_SAIF_unchanged=True,mappings_suppressed=len(selected)))
        print(name,'confirmed opposite aliases suppressed',len(selected),flush=True)

if __name__=='__main__':main()
