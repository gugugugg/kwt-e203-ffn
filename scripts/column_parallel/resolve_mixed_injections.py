from pathlib import Path
import json,sys,shutil
p=Path('reports/optimization/ffn_column_parallel/activity-mapping/native-review-C16/ffn_cp_C16');d=json.loads((p/'corrections-draft.json').read_text());before=p/'analysis-recovery/mixed-source-probe01';before.mkdir(parents=True,exist_ok=True)
for n in ['corrections-draft.json','phase-expectations.json','primary-review-notes.json']:
 shutil.copyfile(p/n,before/n)
for x in (p/'reviewed-draft').glob('*'):shutil.copyfile(x,before/x.name)
rules=[
 ('debug-capture',lambda r:'/cmt_dpc_ena' in r['rtl'],'The original step_req_nxt=set|!clear equals !dbg_entry_taken_ena because set includes !dbg_entry_taken_ena. It is the positive physical NAND cmt_dpc_ena_BAR source; retain step_req_dfflr/dnxt, suppress opposite cmt aliases.'),
 ('JTAG-CDC',lambda r:'/jtag_' in r['rtl'] and r['rtl'].endswith('/rst_n'),'Original CDC rst_n=!jtag_TRST. The actual mux output is positive io_sync_reset/jtag_TRST. Retain that positive source and suppress negative CDC reset aliases.'),
 ('AON-reset',lambda r:'/u_aon_lclkgen_regs/' in r['rtl'] and r['rtl'].endswith('/rst_n'),'Original lclkgen rst_n is !aon_reset; actual ResetCatchAndSync mux emits positive aon_reset/io_sync_reset. Keep positive source.'),
 ('DTCM-write',lambda r:r['inverted'] and '/u_e203_dtcm' in r['rtl'] and (r['rtl'].endswith('/we') or r['rtl'].endswith('/ram_we')) or r['inverted'] and r['rtl'].endswith(('/dtcm_ram_we','/u_sram_wrap_64KX32/WE')),'Original ram_we=!uop_cmd_read; actual shared segment is bypass read bit o_dat[55]. Keep the original read-bit source, suppress complementary WE aliases.'),
 ('ALU-ready',lambda r:r['rtl'].endswith(('/wbck_o_ready','/alu_wbck_i_ready')),'Original ready=!longp_wbck_o_valid under the original arbiter. Actual segment is positive longp_wbck_o_valid; retain it.'),
 ('BIU-valid',lambda r:'/u_e203_biu/' in r['rtl'] and r['inverted'] and any(r['rtl'].endswith(x) for x in ['/o_icb_cmd_valid','/i_icb_cmd_valid','/o_vld','/qout[0]']),'Original FIFO i_rdy=!full and actual qout_BAR/i_icb_cmd_valid_BAR is that ready predicate. Keep i_rdy/arbt-ready sources, suppress complementary valid/full aliases.'),
 ('AXI-AW-ready',lambda r:'/o_axi_aw_fifo/' in r['gate'] and r['inverted'],'Actual positive FIFO full Q is exposed on this segment; keep qout/qout_r and suppress opposite i_rdy/i_axi_awready sources.'),
 ('QSPI-tx-count',lambda r:'/u_sirv_flash_qspi/fifo/txq/io_count[3]' in r['rtl'],'Actual io_count_3_BAR equals FIFO io_tx_ready for this fixed depth. Keep positive io_tx_ready and suppress opposite count-bit alias.')]
removed=[];keep=[]
for r in d['aliases']:
 hits=[(label,why) for label,f,why in rules if f(r)]
 if hits:
  if len(hits)!=1:raise RuntimeError(str(hits))
  removed.append(dict(alias=r,group=hits[0][0],reason=hits[0][1]))
 else:keep.append(r)
assert len(removed)==44,len(removed)
d['aliases']=keep;d['suppressed_opposite_phase_aliases']=[r['alias']['rtl'] for r in removed]
# Make the positive physical truth-source explicit at the one otherwise unnamed debug output.
rtl='soc/u_e203_subsys_main/u_e203_cpu_top/u_e203_cpu/u_e203_core/u_e203_exu/u_e203_exu_commit/u_e203_exu_excp/step_req_dfflr/dnxt[0]'
d['aliases'].append(dict(rtl=rtl,gate='soc/u_sirv_debug_module/u_sirv_debug_csr/cmt_dpc_ena_BAR',inverted=False,reason=rules[0][2],evidence=dict(original='e203_exu_excp.v:310-314,533',native_driver='e203_exu_excp/U42 NAND2V2')))
d['mixed_source_resolution']='Native read_saif -report_inconsistent_annotation proves opposite logical source overwrites on actual segments. Keep structurally positive physical sources; prohibit only the44complementary aliases. SAIF and original map remain unchanged.'
(p/'mixed-source-resolution.json').write_text(json.dumps(dict(removed=removed,old_probe01_retained=True,old_overwrite_diagnostic_retained=True,source_SAIF_unchanged=True,unknown_not_zero_filled=True),indent=2));(p/'corrections-draft.json').write_text(json.dumps(d,indent=2))
sys.path.insert(0,'scripts');from assemble_ffn_column_parallel_review import assemble;assemble('ffn_cp_C16')
print('aliases',len(d['aliases']),'negative',sum(r['inverted'] for r in d['aliases']),'unset',len(removed))

