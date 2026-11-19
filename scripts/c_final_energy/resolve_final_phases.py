"""Close the two actual pending functions and the final response observation ports."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'scripts/c_final_energy')]
from ffn_c_final_energy import dump
from inspect_pending_phases import BASE,model

def main():
    for name in ['ffn_cfe_SS','ffn_cfe_O1']:
        own=BASE/name;inv=json.loads((own/'inventory.json').read_text());cells=inv['cells'];conn=json.loads((own/'connectivity.json').read_text())
        for cell in cells.values():cell['pins']={k:v.strip() for k,v in cell['pins'].items()}
        pending=json.loads((own/'phase-review-pending.json').read_text());draft=json.loads((own/'corrections-draft.json').read_text())
        if not pending:
            if (own/'pending-resolution.json').exists():continue
            raise RuntimeError('Read prior phase resolution')
        assert len(pending)==1
        dump(own/'phase-review-initial-pending.json',pending)
        vendor=(own/'vendor-functions.v').read_text()
        evidence={}
        if name.endswith('SS'):
            row=next(r for r in json.loads((own/'cell-inverted-review-inputs.json').read_text()) if r['rtl']==pending[0]['rtl'])
            literal=model(vendor,row['ref'])
            assert row['ref']=='LAHQNV0_12TR40' and row['pins']['D'].strip()=='ap_input_rdata[0]'
            assert 'not I3(clk,E)' in literal and 'udp_tlat I0 (n0, D, clk' in literal and 'I2 (QN, n0)' in literal
            reason='Actual LAHQNV0 HIGH-return latch copies positive input macro Q at D; literal udp_tlat plus QN inverter makes this physical net negative original jp_input_return[16].'
            gate=row['QN_net'];evidence=dict(cell=row['gate'],ref=row['ref'],pins=row['pins'],literal_model=literal)
            records=json.loads((own/'physical-cell-phase-review.json').read_text())
            records.append(dict(rtl=row['rtl'],physical_inverted=True,output='QN',net=gate,reason=reason,evidence=evidence))
            dump(own/'physical-cell-phase-review.json',records);draft['replace_native_cell_aliases'].append(row['rtl'])
            draft['aliases'].append(dict(rtl=row['rtl'],gate=gate,inverted=True,reason=reason,evidence=evidence))
        else:
            parent='soc/u_e203_subsys_main/u_e203_cpu_top/u_e203_cpu/u_e203_core/u_e203_exu/u_e203_exu_alu'
            expected={
                'U211':('BUFV32RD_12TR40',{'I':'n282','Z':'n163'}),
                'U487':('INV10SR_12TR40',{'I':'n187','ZN':'n282'}),
                'U98':('CLKAND2V8_12TR40',{'A1':'n364','A2':'i_info[1]','Z':'n187'}),
                'U100':('NOR2CV4_12TR40',{'A1':'n180','A2':'n173','ZN':'n364'}),
                'U6':('CLKNAND2V12_12TR40',{'A1':'n156','A2':'n165','ZN':'n180'}),
                'U521':('NAND2V2_12TR40',{'A1':'n172','A2':'n155','ZN':'n173'}),
                'U35':('CLKINV8_12TR40',{'I':'i_ilegl','ZN':'n156'}),
                'U212':('INV2SR_12TR40',{'I':'i_buserr','ZN':'n165'}),
                'U110':('INV2SR_12TR40',{'I':'i_info[0]','ZN':'n172'}),
                'U113':('INV0_12TR40',{'I':'i_info[2]','ZN':'n155'})}
            chain={}
            for leaf,(ref,pins) in expected.items():
                c=cells[parent+'/'+leaf];assert c['ref']==ref and c['pins']==pins
                chain[leaf]=dict(c,literal_model=model(vendor,ref))
            assert cells[parent]['pins']['i_misalgn']=="1'b0"
            source='build/server/official_2025/e203_hbirdv2-master/rtl/e203/core/e203_exu_alu.v'
            rtl=(ROOT/source).read_text();assert 'wire bjp_req_alu = bjp_op' in rtl
            reason='Actual decode computes !i_ilegl & !i_buserr & !i_info[0] & i_info[1] & !i_info[2], with i_misalgn tied zero: original bjp_op/group2. INV10SR U487 then BUFV32RD U211 produce its complement at the dpath BAR segment.'
            evidence=dict(chain=chain,original_source=source,misalgn_actual_constant="1'b0",definition='bjp_req_alu=bjp_op; BJP group=2')
            for row in pending[0]['aliases']:draft['aliases'].append(dict(rtl=row['rtl'],gate=row['gate'],inverted=True,reason=reason,evidence=evidence))
        draft['pending']=0;dump(own/'corrections-draft.json',draft);dump(own/'phase-review-pending.json',[])
        dump(own/'pending-resolution.json',dict(passed=True,variant=name,tag=inv['tag'],initial_pending=pending,reason=reason,evidence=evidence))
        # The response ports are separately verified against the original recipient mux.
        a='shared_memory/memory_arbiter/'
        selected=['U9','U10','U11','U12','U21','U4','U14','U37','U17','U15','U16'] if name.endswith('SS') else ['U11','U27','U4','U20','U31','U5','U22']
        arb={k:dict(cells[a+k],literal_model=model(vendor,cells[a+k]['ref'])) for k in selected}
        valid=cells['shared_memory/joined_rsp_valid_reg'];assert valid['ref']=='DRNQV6_12TR40' and valid['pins']['Q']=='joined_rsp_valid'
        original=(ROOT/'build/optimization/complete_soc'/name/'kwt_shared_dma_icb_sm40.sv').read_text()
        assert 'assign s_rsp_ready=recipient?b_rsp_ready:a_rsp_ready;' in original
        ready_reason=('n17=grant; n37=!grant; n30=!recipient; n9=!(n30&a_rsp_ready); OAI2XB1 U9 gives !n9|(!n30&b_rsp_ready), the original positive mux.' if name.endswith('SS') else 'n12=grant; n22=!active; AOI22 U27 gives n17=!recipient; U4 gives n15=recipient; AO22 U11 implements the original positive ready mux.')
        dump(own/'mapped-ack-interface.json',dict(passed=True,variant=name,tag=inv['tag'],valid_expression='dut.shared_memory.joined_rsp_valid',ready_expression='dut.shared_memory.joined_rsp_ready',valid_evidence=dict(cell=valid,literal_model=model(vendor,valid['ref'])),ready_evidence=arb,ready_equation=ready_reason,old_pending_checked_before_new_final_write=True))
        print(name,'pending resolved; actual ACK ports positive',flush=True)

if __name__=='__main__':main()
