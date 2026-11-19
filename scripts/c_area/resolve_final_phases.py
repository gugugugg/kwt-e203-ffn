"""Close this round's actual pending encodings and mapped ACK mux functions."""
from pathlib import Path
import itertools,json,re,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_area import REPORT,dump
BASE=REPORT/'activity-mapping/native-review-first'

def main():
    for name in ['ffn_car_AR','ffn_car_D1']:
        out=BASE/name;inv=json.loads((out/'inventory.json').read_text());cells=inv['cells'];draft=json.loads((out/'corrections-draft.json').read_text());pending=json.loads((out/'phase-review-pending.json').read_text())
        vendor=(out/'vendor-functions.v').read_text();netlist=(ROOT/'build/server'/('complete_soc_sm40_'+inv['tag'])/'netlist.v').read_text()
        modules={m.group(1):m.group(2) for m in re.finditer(r'module\s+(\w+)\s*\(([\s\S]*?)endmodule',netlist)}
        def cell(path):
            c=cells[path];return dict(c,pins={k:v.strip() for k,v in c['pins'].items()})
        def literal(ref):return re.search(r'(?m)^\s*module\s+'+re.escape(ref)+r'\s*\([\s\S]*?\bendmodule',vendor).group()
        def evidence(path):
            c=cell(path);return dict(cell=path,**c,literal_model=literal(c['ref']))
        resolved=[];dump(out/'phase-review-initial-pending.json',pending)
        for row in pending:
            if row['kind']=='cell_encoding':
                r=next(x for x in json.loads((out/'cell-inverted-review-inputs.json').read_text()) if x['rtl']==row['rtl']);p=r['gate'].rsplit('/',1)[0]
                assert name.endswith('AR') and r['ref']=='EDQNV6_12TR40'
                driver=cell(p+'/U2');assert driver['ref']=='CLKINV0_12TR40' and driver['pins']==dict(I='dnxt_0_',ZN='n2')
                ev=dict(state=evidence(r['gate']),D_driver=evidence(p+'/U2'),equation='D=!dnxt; literal EDQN QN=!registered(D), so QN=registered(dnxt) with original enable')
                reason='Actual CLKINV0 on dnxt plus literal EDQN output inverter cancel; positive original qout is retained with its native encoded-positive cell rule.'
                records=json.loads((out/'physical-cell-phase-review.json').read_text());records.append(dict(rtl=r['rtl'],physical_inverted=False,output='QN',net=r['QN_net'],reason=reason,evidence=ev));dump(out/'physical-cell-phase-review.json',records)
                resolved.append(dict(row=row,physical_inverted=False,reason=reason,evidence=ev));continue
            key=row['segment'];ev={}
            if '/icb2mem_dfflr/lden_BAR' in key:
                instances=[]
                for path,mod in inv['hierarchy'].items():
                    if path.endswith(('icb2mem_dfflr','icb2itcm_dfflr')):
                        body=modules[mod];assert 'I(lden_BAR)' in re.sub(r'\s','',body)
                        instances.append(dict(path=path,module=mod,literal_mapped_module=body))
                assert len(instances)==2
                ev=dict(instances=instances,original_source='build/server/official_2025/e203_hbirdv2-master/rtl/e203/core/e203_ifu_ift2icb.v',equation='e=!lden_BAR; D=!( (e|!q) & !(e&dnxt) ) = e?dnxt:q; reset-zero DRNQ, so lden_BAR=!original lden')
                reason='Own mapped dfflr input is inverted before its unchanged load/hold mux; its original load qualification is ifu_icb_cmd_hsked, hence physical lden_BAR is negative lden.'
            elif key=='shared_memory/memory_arbiter/b_cmd_read_BAR':
                p='soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/dma_frontend/loading_dma/output_transfer_reg';c=cell(p)
                assert name.endswith('D1') and c['ref']=='DRNQV6_12TR40' and c['pins']['Q']=='mem_cmd_read_BAR'
                source=ROOT/'build/optimization/rtl_sources'/name/'encoder/kwt_ld_engine.sv';assert 'assign mem_cmd_read=!output_transfer;' in re.sub(r'\s+',' ',source.read_text())
                ev=dict(state=evidence(p),original_source=source.relative_to(ROOT).as_posix(),equation='Physical positive output_transfer Q = !original mem_cmd_read; original output_transfer source remains positive')
                reason='Own output_transfer positive Q directly drives the physical BAR segment; all listed logical memory-read aliases are its complement.'
            elif '/rowbuf_cnt_d_dfflr/qout_0__BAR' in key:
                p=key.rsplit('/',1)[0];q=cell(p+'/qout_r_reg_0_');assert q['ref']=='DSNQV8_12TR40' and q['pins']['SDN']=='rst_n'
                assert cell(p+'/U3')['pins']==dict(A1='lden',A2='qout_0__BAR',B='n5',Z='n4')
                assert cell(p+'/U4')['pins']==dict(A1='lden',A2='dnxt[0]',ZN='n5')
                assert all(((en or qb) and not(en and d))==(not d if en else qb) for en,qb,d in itertools.product([False,True],repeat=3))
                ev=dict(cells=[evidence(p+'/'+s) for s in ['U3','U4','qout_r_reg_0_']],equation='Qbar_next=(en|Qbar)&!(en&dnxt)=en?!dnxt:Qbar; SDN sets Qbar=1 while original reset-zero qout=0')
                reason='Own set-one Q stores the complement of the original reset-zero rowbuf bit, with the full hold/load D equation verified.'
            elif key.endswith('/core/layer_request_BAR'):
                p=key.rsplit('/',1)[0];expected={'U2630':('OR2V0_12TR40',dict(A1='n29579',A2='n757',Z='layer_request_BAR')),'U25863':('CLKBUFV6_12TR40',dict(I='state[2]',Z='n29579')),'U3738':('NAND2CV0_12TR40',dict(A1='n29739',A2='n29340',ZN='n757')),'U26027':('CLKBUFV6_12TR40',dict(I='state[1]',Z='n29739')),'U3737':('NOR2CV0_12TR40',dict(A1='state[0]',A2='state[3]',ZN='n29340'))}
                for leaf,(ref,pins) in expected.items():assert cell(p+'/'+leaf)['ref']==ref and cell(p+'/'+leaf)['pins']==pins
                states=[cell(p+'/state_reg_%d_'%bit) for bit in range(4)];assert all(c['ref']=='DRNQV0_12TR40' and c['pins']['Q']=='state[%d]'%bit for bit,c in enumerate(states))
                truth=[dict(state=s,physical=bool((s>>2)&1) or not(bool((s>>1)&1) and not(bool(s&1) or bool((s>>3)&1)))) for s in range(16)]
                assert all(x['physical']==(x['state']!=2) for x in truth)
                ev=dict(cells=[evidence(p+'/'+k) for k in expected],state_registers=states,truth_table=truth,equation='s2 | !(s1 & !(s0|s3)) = !(state[3:0]==2); original WAIT_LAYER=2, upper state bit optimized away')
                reason='Own actual OR/NAND/NOR cone implements the complement of the original binary WAIT_LAYER predicate.'
            else:raise RuntimeError('Read this own pending function '+key)
            for alias in row['aliases']:draft['aliases'].append(dict(rtl=alias['rtl'],gate=alias['gate'],inverted=True,reason=reason,evidence=ev))
            resolved.append(dict(row=row,physical_inverted=True,reason=reason,evidence=ev))
        draft['pending']=0;dump(out/'corrections-draft.json',draft);dump(out/'phase-review-pending.json',[]);dump(out/'pending-resolution.json',dict(passed=True,variant=name,tag=inv['tag'],resolved=resolved))
        a='shared_memory/memory_arbiter/';leaves=['U5','U7','U9','U26','U31','U35','U8'] if name.endswith('AR') else ['U16','U23','U27','U28','U6','U7','U8','U32','U29']
        # Literal gate equations use the actual positive register outputs in each final.
        for active,owner,hv,ho,av,pref,bv,ar,br in itertools.product([False,True],repeat=9):
            grant=ho if hv else bv and (not av or pref);recipient=owner if active else grant
            if name.endswith('AR'):
                n10=not((not av or pref) and bv);n16=not(hv and ho);g=not((hv or n10) and n16)
            else:
                n7=not((not av or pref) and not hv);n15=not(hv and ho);g=not((not bv or n7) and n15)
            nr=not((active and owner) or (g and not active));actual=(nr and ar) or (not nr and br)
            assert actual==(br if recipient else ar)
        v=cell('shared_memory/joined_rsp_valid_reg');assert v['ref']=='DRNQV6_12TR40' and v['pins']['Q']=='joined_rsp_valid'
        source=ROOT/'build/optimization/complete_soc'/name/'kwt_shared_dma_icb_sm40.sv';assert 'assign s_rsp_ready=recipient?b_rsp_ready:a_rsp_ready;' in source.read_text()
        dump(out/'mapped-ack-interface.json',dict(passed=True,variant=name,tag=inv['tag'],valid_expression='dut.shared_memory.joined_rsp_valid',ready_expression='dut.shared_memory.joined_rsp_ready',valid_evidence=evidence('shared_memory/joined_rsp_valid_reg'),ready_evidence=[evidence(a+k) for k in leaves],ready_equation='positive recipient mux; grant=held_valid?held_owner:(b_valid&&(!a_valid||prefer_b)); recipient=active?owner:grant',truth_table_cases=512,truth_table_mismatches=0,original_source=source.relative_to(ROOT).as_posix(),old_pending_checked_before_new_final_write=True))
        print('C_AREA_OWN_PENDING_RESOLVED',name,len(resolved),'ACK512passed',flush=True)

if __name__=='__main__':main()
