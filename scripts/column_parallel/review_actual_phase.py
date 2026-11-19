from pathlib import Path
import json,re,sys
root=Path('.').resolve();p=root/'reports/optimization/ffn_column_parallel/activity-mapping/native-review-C16/ffn_cp_C16'
s=json.loads((p/'corrections-draft.json').read_text());(p/'corrections-before-manual.json').write_text(json.dumps(s,indent=2))
inv=json.loads((p/'inventory.json').read_text());conn=json.loads((p/'connectivity.json').read_text());c=inv['cells'];pending=json.loads((p/'phase-review-pending.json').read_text())
ph=json.loads((p/'physical-cell-phase-review.json').read_text());rows=json.loads((p/'cell-inverted-review-inputs.json').read_text());by={x['rtl']:x for x in rows}
for r in pending:
 if r['kind']=='cell_encoding' and '/jp_shift_return[' in r['rtl']:
  x=by[r['rtl']];assert x['ref']=='LALQNV6_12TR40' and x['pins']['EN'].strip()=='clk' and x['pins']['D'].strip().startswith('shift_rdata[')
  note='Actual IR-derived RTL is always_latch if(!clk) jp_shift_return=shift_rdata. Own LALQNV6 uses udp_tlat(n0,D,EN,...) and not(QN,n0); the LOW latch D is uncomplemented macro shift_rdata. Physical QN is negative RTL and must be mapped as an inverted net, not a cell rule.'
  ev=dict(ref=x['ref'],pins=x['pins'],native_QN=x['QN_net'],native_D=x['D_net'],original='build/optimization/rtl_sources/ffn_cp_C16/encoder/kwt_encoder.sv:159',vendor='vendor-functions.v:LALQNV6_12TR40 + vendor-udp.v:udp_tlat')
  s['aliases'].append(dict(rtl=r['rtl'],gate=x['QN_net'],inverted=True,reason=note,evidence=ev));s['replace_native_cell_aliases'].append(r['rtl'])
  ph.append(dict(rtl=r['rtl'],physical_inverted=True,output='QN',net=x['QN_net'],reason=note,evidence=ev))
 elif r['kind']=='net_semantics' and '/icb2mem_dfflr/lden_BAR' in r['segment']:
  note='Actual sirv_gnrl_dfflr_DW1_35: n3=!lden_BAR, n4=!(n3&dnxt), n5=!qout, n6=!((n3|n5)&n4)=(n3?dnxt:qout). Thus lden_BAR is exactly the complement of original positive lden, irrespective of the upstream OR2 implementation. Both IFU aliases are negative on this connected segment.'
  for x in r['aliases']:s['aliases'].append(dict(rtl=x['rtl'],gate=x['gate'],inverted=True,reason=note,evidence=dict(actual_module='sirv_gnrl_dfflr_DW1_35',original='build/server/official_2025/e203_hbirdv2-master/rtl/e203/general/sirv_gnrl_dffs.v',drivers=r['drivers'])))
 else:raise RuntimeError('Unreviewed pending '+str(r))
s['pending']=0;s['manual_C16_pending_resolved']=len(pending)
(p/'corrections-draft.json').write_text(json.dumps(s,indent=2));(p/'physical-cell-phase-review.json').write_text(json.dumps(ph,indent=2))
sys.path.insert(0,'scripts');from assemble_ffn_column_parallel_review import assemble
assemble('ffn_cp_C16')
col=json.loads((p/'corrected-injection-collisions.json').read_text());print('COLLISIONS',len(col))
for x in col:
 print('SEGMENT',x['segment'])
 for r in x['sources']:print(r['rtl'],r['inverted'],r['raw'])
ex=json.loads((p/'phase-expectations.json').read_text());print('UNRESOLVED',len(ex['unresolved']));print(json.dumps(ex['unresolved'][:8],indent=2))
