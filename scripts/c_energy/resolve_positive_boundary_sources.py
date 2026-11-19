"""Use positive sources where the native boundary has both ready/read/reset semantics."""
from pathlib import Path
import json,sys,shutil
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_energy import REPORT,dump

def main():
    p=REPORT/'activity-mapping/native-review-first/ffn_cen_SL';draft=json.loads((p/'corrections-draft.json').read_text());con=json.loads((p/'connectivity.json').read_text());act=json.loads((p/'saif-index.json').read_text())['activity'];reps=con['representatives']
    b=p/'analysis-recovery/negative-boundary-before-positive-source';b.mkdir(parents=True,exist_ok=True)
    for f in [p/'corrections-draft.json']+list((p/'reviewed-draft').glob('*')):
        if f.is_file():shutil.copyfile(f,b/f.name)
    cpu='soc/u_e203_subsys_main/u_e203_cpu_top/u_e203_cpu';biu=cpu+'/u_e203_core/u_e203_biu'
    choices=[
        ('/aonrst_catch/io_sync_reset','soc/u_sirv_aon_top/u_sirv_aon_wrapper/aonrst_catch/io_sync_reset', ['soc/u_sirv_aon_top/u_sirv_aon_wrapper/aon_reset','soc/u_sirv_aon_top/u_sirv_aon_wrapper/aonrst_catch/io_sync_reset']),
        ('/u_sram_wrap_64KX32/memory/we_BAR',cpu+'/u_e203_dtcm_ctrl/u_sram_icb_ctrl/u_byp_icb_cmd_buf/o_dat[55]',[cpu+'/u_e203_dtcm_ctrl/u_sram_icb_ctrl/u_byp_icb_cmd_buf/o_dat[55]']),
        ('/u_biu_icb_splt/i_icb_cmd_valid_BAR',biu+'/u_sirv_gnrl_icb_buffer/u_sirv_gnrl_cmd_fifo/i_rdy',[biu+'/u_biu_icb_arbt/o_icb_cmd_ready',biu+'/u_sirv_gnrl_icb_buffer/i_icb_cmd_ready',biu+'/u_sirv_gnrl_icb_buffer/u_sirv_gnrl_cmd_fifo/i_rdy']),
    ]
    suppressed=set(draft['suppressed_opposite_phase_aliases']);replacements=[]
    for marker,rtl,restore in choices:
        rows=[r for r in draft['aliases'] if reps.get(r['gate'],r['gate']).endswith(marker)]
        if not rows or any(not r['inverted'] for r in rows):raise RuntimeError('Read actual remaining negative-only boundary group')
        representative=reps.get(rows[0]['gate'],rows[0]['gate']);dr=con['drivers'][representative][0]
        draft['aliases']=[r for r in draft['aliases'] if r not in rows]
        suppressed.update(r['rtl'] for r in rows);suppressed.difference_update(restore)
        row=dict(rtl=rtl,gate=representative,gate_pin=dr['cell']+'/'+dr['pin'],inverted=False,
                 reason='Use original positive reset/read/ready source at the actual leaf output; exclude opposite original negative aliases from automatic matching.',
                 evidence=dict(native_probe5_negative_group_mismatches=len(rows),driver=dr,source=act[rtl],removed_negative_aliases=[r['rtl'] for r in rows]))
        draft['aliases'].append(row);replacements.append(row)
    draft['suppressed_opposite_phase_aliases']=sorted(suppressed);draft['positive_boundary_sources']=replacements
    dump(p/'corrections-draft.json',draft);dump(p/'positive-boundary-sources.json',dict(replacements=replacements,suppressed_count=len(suppressed),source_SAIF_unchanged=True))
    print('C_ENERGY_POSITIVE_BOUNDARIES',len(draft['aliases']),sum(r['inverted'] for r in draft['aliases']),len(suppressed),flush=True)

if __name__=='__main__':main()
