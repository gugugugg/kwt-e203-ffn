"""Resolve the actual reset buffer chain; preserve all original source representations."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_final_energy import REPORT,dump

def main():
    base=REPORT/'activity-mapping/native-review-first'
    p=base/'ffn_cfe_O1';inv=json.loads((p/'inventory.json').read_text());draft=json.loads((p/'corrections-draft.json').read_text())
    prefix='soc/u_e203_subsys_main/u_e203_subsys_plic/u_sirv_plic_top/u_sirv_plic_man/'
    cells=inv['cells']
    assert cells[prefix+'U463']['pins']==dict(I='rst_n',ZN='n364')
    assert cells[prefix+'U3']['pins']==dict(I='n364',ZN='n363')
    assert cells[prefix+'U3']['ref']==cells[prefix+'U463']['ref']=='CLKINV12_12TR40'
    changed=[]
    for row in draft['aliases']:
        if not row['rtl'].startswith(prefix):continue
        if row['gate'] not in json.loads((p/'connectivity.json').read_text())['representatives']:continue
        if row['rtl'].endswith('/rst_n'):
            changed.append(dict(before=dict(row),after_inverted=False));row.update(inverted=False,reason='Actual U463 !rst_n followed by U3 inversion gives positive rst_n on n363. Original reset-low generic flop port is positive here; the final BAR spelling is not a phase rule.')
        elif row['rtl'].endswith('/reset'):
            row['reason']='Actual U463 !rst_n followed by U3 inversion gives positive rst_n on n363; original LevelGateway reset=~rst_n, so its semantic alias is negative on this segment.'
    dump(p/'reset-double-inverter-review.json',dict(passed=True,tag=inv['tag'],actual_cells={k:cells[prefix+k] for k in ['U463','U3']},original_source='build/server/official_2025/e203_hbirdv2-master/rtl/e203/perips/sirv_plic_man.v',source_reset='LevelGateway.reset(~rst_n); irq_thod_dfflr(...,rst_n)',changed=changed))
    dump(p/'corrections-draft.json',draft)
    from assemble_ffn_c_final_energy_review import assemble
    for name in ['ffn_cfe_SS','ffn_cfe_O1']:
        assemble(name);p=base/name;rows=json.loads((p/'corrected-injection-collisions.json').read_text());unknown=[];ambiguous=[]
        for row in rows:
            if any('r_gpio_sync1[' in s['rtl'] and s['raw']['T0']+s['raw']['T1']==0 for s in row['sources']):
                unknown.append(dict(segment=row['segment'],reason='Original uninitialized GPIO register alias and directly observed interface aliases retained; do not fill the unknown.',sources=row['sources']));continue
            assert row['segment'].endswith('/u_e203_biu/u_biu_icb_splt/i_icb_cmd_valid_BAR')
            stats=[]
            for s in row['sources']:
                raw=s['raw'];stats.append((raw['T0'] if s['inverted'] else raw['T1'],raw['TC'],raw['T0']+raw['T1'],raw['TX']))
            assert len(set(s[1:] for s in stats))==1 and max(s[0] for s in stats)-min(s[0] for s in stats)==1
            ambiguous.append(dict(segment=row['segment'],reason='Current literal CLKINV0 drives negative FIFO valid. Original i_rdy=!vec_r[1] and o_vld=vec_r[1] have complementary recorded durations differing by one SAIF time unit. Retain all original aliases and compare native output with these explicit source representations separately.',sources=row['sources'],numeric_tolerance_added=False))
        dump(p/'injection-source-ambiguities.json',dict(unknown_alias_groups=unknown,audited_ambiguous_groups=ambiguous,original_SAIF_unchanged=True,mappings_suppressed=0))
        print(name,'original unknown groups',len(unknown),'source representations',len(ambiguous),flush=True)

if __name__=='__main__':main()
