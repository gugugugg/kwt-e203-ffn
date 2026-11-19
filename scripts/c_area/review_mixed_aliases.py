"""Preserve unknown GPIO aliases and resolve the actual AR FIFO double inversion."""
import json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_area import REPORT,dump
from assemble_ffn_c_area_review import assemble
base=REPORT/'activity-mapping/native-review-first'
for name in ['ffn_car_AR','ffn_car_D1']:
    p=base/name;draft=json.loads((p/'corrections-draft.json').read_text());inv=json.loads((p/'inventory.json').read_text());resolution=[]
    if name.endswith('AR'):
        rtl='soc/u_e203_subsys_main/u_e203_cpu_top/u_e203_cpu/u_e203_itcm_ctrl/u_sram_icb_ctrl/u_byp_icb_cmd_buf/u_bypbuf_fifo/dp_gt0.vec_31_dfflr/qout[0]';row=next(x for x in draft['aliases'] if x['rtl']==rtl);dump(p/'analysis-recovery/FIFO-qout-before.json',row)
        path=row['gate'].rsplit('/',1)[0];cells=inv['cells'];q=cells[path+'/qout_r_reg_0_'];assert q['ref']=='DRNQV6_12TR40' and q['pins']['Q']=='n10'
        expected={'U5':('DEL2V0_12TR40',dict(I='n10',Z='n7')),'U7':('CLKINV0_12TR40',dict(I='n7',ZN='n8')),'U6':('CLKINV0_12TR40',dict(I='n8',ZN='qout[0]'))}
        for k,(ref,pins) in expected.items():assert cells[path+'/'+k]['ref']==ref and cells[path+'/'+k]['pins']==pins
        ev=dict(positive_register=q,chain={k:cells[path+'/'+k] for k in expected},equation='qout = !(!(DELAY(positive Q))) = positive original FIFO full; ready aliases on this same segment require opposite semantics')
        row.update(inverted=False,reason='Own actual positive reset-zero DRNQ followed by DEL and two literal inverters restores positive qout, while shared i_rdy aliases remain negative.',evidence=ev);resolution.append(dict(rtl=rtl,physical_inverted=False,evidence=ev))
    dump(p/'corrections-draft.json',draft);dump(p/'mixed-alias-resolution.json',dict(passed=True,variant=name,tag=inv['tag'],resolved=resolution))
    assemble(name)
    collisions=json.loads((p/'corrected-injection-collisions.json').read_text());unknown=[]
    for row in collisions:
        assert any('r_gpio_sync1[' in x['rtl'] and x['raw']['T0']+x['raw']['T1']==0 for x in row['sources'])
        unknown.append(dict(segment=row['segment'],sources=row['sources'],reason='Original internal GPIO TX and known boundary aliases coexist; values and source ambiguity retained without zero filling'))
    dump(p/'injection-source-ambiguities.json',dict(unknown_alias_groups=unknown,audited_ambiguous_groups=[],original_SAIF_unchanged=True))
    print('C_AREA_MIXED_ALIASES_REVIEWED',name,'unknown_groups',len(unknown),flush=True)
