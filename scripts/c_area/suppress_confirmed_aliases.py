"""Resolve only this final's observed opposite-source overwrites and duplicate producers."""
from pathlib import Path
import json,shutil,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_area import REPORT,dump
from assemble_ffn_c_area_review import assemble
for name in ['ffn_car_AR','ffn_car_D1']:
    p=REPORT/'activity-mapping/native-review-first'/name;draft=json.loads((p/'corrections-draft.json').read_text());conn=json.loads((p/'connectivity.json').read_text());inv=json.loads((p/'inventory.json').read_text());verdict=json.loads((p/'probe-attempt-01/comparison-verdict.json').read_text())
    before=p/'analysis-recovery/probe01-source-overwrite';before.mkdir(parents=True,exist_ok=True)
    for leaf in ['corrections-draft.json','phase-expectations.json','reviewed-draft/'+name+'.tcl','reviewed-draft/'+name+'.json','reviewed-draft/'+name+'-native-map-filtered.tcl']:
        target=before/leaf;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(str(p/leaf),str(target))
    groups={conn['representatives'].get(e['net'],e['net']):e for e in verdict['errors']};opposite=[];duplicates=[];records=[]
    for key,e in groups.items():
        sources=e['sources'];negative=[x['rtl'] for x in sources if x['inverted']];positive=[x['rtl'] for x in sources if not x['inverted']];dedup=[]
        drivers=conn['drivers'].get(key,[]);literal_drivers=[dict(d,actual_cell=inv['cells'][d['cell']]) for d in drivers]
        if '/jtag_' in key and key.endswith('/rst_n_BAR'):
            reason='Own CLKMUX emits positive io_sync_reset/jtag_TRST; retain those direct physical sources and block opposite CDC reset-low aliases exposed by probe01.'
        elif '/aonrst_catch/io_sync_reset' in key:
            reason='Own AON CLKMUX emits active-high reset; retain direct reset-high expressions and block the opposite lclkgen rst_n aliases exposed by probe01.'
        elif '/u_e203_dtcm_ram/' in key and key.endswith('/we_BAR'):
            reason='Original sirv_1cyc_sram_ctrl has ram_we=!uop_cmd_read. Actual buffer drives o_dat[55], the positive read bit; block opposite write aliases. Prefer the actual producer o_dat[55] over the duplicate downstream uop_cmd_read statistics.'
            assert any(x.endswith('/o_dat[55]') for x in positive)
            dedup=[x for x in positive if x.endswith('/uop_cmd_read')]
        elif '/icb2mem_dfflr/dnxt[0]' in key:
            reason='Own NAND4 drives positive BIU selection at icb2mem dnxt, while icb2itcm dnxt is its complement and is inverted inside the mapped dfflr. Retain the positive memory-selection source.'
            assert any('/icb2mem_dfflr/dnxt[0]' in x for x in positive)
        elif key.endswith('/cmt_dpc_ena_BAR'):
            reason='Original step_req_nxt=step_req_set|!step_req_clr, step_req_set=K&!dbg_entry_taken_ena, step_req_clr=dbg_entry_taken_ena=cmt_dpc_ena. Absorption yields step_req_nxt=!cmt_dpc_ena, the actual NAND output and positive step_req_dfflr dnxt producer. Block opposite cmt_dpc_ena aliases.'
            assert any('/step_req_dfflr/dnxt[0]' in x for x in positive)
        elif key.endswith('/alu_wbck_i_ready_BAR'):
            reason='Original wbck_i_ready is constant one; alu_wbck_i_ready=!longp_wbck_i_valid. Actual AND3 Z is positive longp_wbck_o_valid. Block opposite ready aliases and prefer the actual producer over the duplicate downstream valid port statistics.'
            assert any(x.endswith('/longp_wbck_o_valid') for x in positive)
            dedup=[x for x in positive if x.endswith('/longp_wbck_i_valid')]
        else:raise RuntimeError('Read this actual probe01 mismatch '+key)
        opposite+=negative;duplicates+=dedup
        records.append(dict(segment=key,reason=reason,observed=e,opposite_aliases=negative,deduplicated_positive_aliases=dedup,retained_producers=[x for x in positive if x not in dedup],literal_drivers=literal_drivers))
    draft['suppressed_opposite_phase_aliases']=sorted(set(opposite));draft['deduplicated_positive_aliases']=sorted(set(duplicates));dump(p/'corrections-draft.json',draft)
    dump(p/'opposite-semantic-alias-review.json',dict(passed=True,variant=name,tag=inv['tag'],groups=records,opposite_alias_count=len(set(opposite)),positive_producer_dedup_count=len(set(duplicates)),original_map_and_SAIF_unchanged=True,manual_values_added=False,reason='Exact observed native overwrite; one physical producer retained, original per-alias representations preserved in recovery'))
    assemble(name)
    collisions=json.loads((p/'corrected-injection-collisions.json').read_text());unknown=[]
    for row in collisions:
        assert any('r_gpio_sync1[' in x['rtl'] and x['raw']['T0']+x['raw']['T1']==0 for x in row['sources'])
        unknown.append(dict(segment=row['segment'],sources=row['sources'],reason='Original unknown GPIO and measured boundary representations retained'))
    dump(p/'injection-source-ambiguities.json',dict(unknown_alias_groups=unknown,audited_ambiguous_groups=[],original_SAIF_unchanged=True))
    print('C_AREA_OBSERVED_ALIAS_OVERWRITE_RESOLVED',name,'opposite',len(set(opposite)),'duplicate_positive',len(set(duplicates)),flush=True)
