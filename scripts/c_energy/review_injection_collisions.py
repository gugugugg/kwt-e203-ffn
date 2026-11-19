"""Retain source ambiguities without changing original activity or suppressing valid aliases."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_energy import REPORT,dump

def main():
    p=REPORT/'activity-mapping/native-review-first/ffn_cen_SL'
    rows=json.loads((p/'corrected-injection-collisions.json').read_text())
    unknown=[];ambiguous=[]
    for row in rows:
        if any('r_gpio_sync1[' in s['rtl'] and s['raw']['T0']+s['raw']['T1']==0 for s in row['sources']):
            unknown.append(dict(segment=row['segment'],reason='Uninitialized GPIO register alias coexists with directly recorded interface aliases; retain the original unknown and the actual read_saif result.',sources=row['sources']))
            continue
        suffix='/u_e203_biu/u_biu_icb_splt/i_icb_cmd_valid_BAR'
        if not row['segment'].endswith(suffix):raise RuntimeError('Read an unreviewed non-GPIO source conflict')
        # Actual FIFO vec[1] Q and its literal inverter drive valid and !valid.
        # Separate recorded aliases differ by 1 ns; no uniquely exposed annotation provider.
        stats=[]
        for s in row['sources']:
            raw=s['raw'];stats.append((raw['T1'] if not s['inverted'] else raw['T0'],raw['TC'],raw['T0']+raw['T1'],raw['TX']))
        if len(set(s[1:] for s in stats))!=1 or max(s[0] for s in stats)-min(s[0] for s in stats)!=1:raise RuntimeError('Read the actual source difference')
        ambiguous.append(dict(segment=row['segment'],reason='Actual DP1 FIFO assigns i_rdy=!vec_r[1], o_vld=vec_r[1]; this native segment is CLKINV0 of positive qout. Seven original SAIF aliases record complementary durations differing by 1 ns. Keep every valid mapping. Check native text against recorded representations and report this separately from uniquely predicted comparisons.',sources=row['sources'],source_rtl='third_party/e203_hbirdv2/rtl/e203/general/sirv_gnrl_bufs.v',source_lines=[468,477,517],numeric_tolerance_added=False))
    dump(p/'injection-source-ambiguities.json',dict(unknown_alias_groups=unknown,audited_ambiguous_groups=ambiguous,original_SAIF_unchanged=True,mappings_suppressed=0))
    print('C_ENERGY_SOURCE_CONFLICTS_RETAINED',len(unknown),len(ambiguous),flush=True)

if __name__=='__main__':main()
