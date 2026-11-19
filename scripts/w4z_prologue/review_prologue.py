"""Resolve the prologue-specific encodings from its connected final netlist."""
import json
from pathlib import Path
import re
import shutil
import sys

from build_prologue import NAME
from phase_overlap import ROOT, bind, phase
from resolve_overlap_phase import resolve


def main():
    _, _, _, review = bind('P2', variant=NAME)
    phase.local_review('inspect')
    from sr_area_phase_review import native_index

    def read(name):
        return json.loads((review/name).read_text())

    def write(name, value):
        (review/name).write_text(json.dumps(value, indent=2)+'\n')

    pending_path = review/'phase-review-pending.json'
    saved = pending_path.read_bytes()
    pending = read(pending_path.name)
    specialized = [r for r in pending if (r.get('rtl','').rsplit('/',1)[-1].startswith(
                   ('jp_input_return[', 'operand_weight[', 'owner')) or r['kind']=='net_semantics')]
    write(pending_path.name, [r for r in pending if r not in specialized])
    try:
        resolve('P2', variant=NAME)
    finally:
        pending_path.write_bytes(saved)

    inv, conn = read('inventory.json'), read('connectivity.json')
    cells, reps = inv['cells'], conn['representatives']
    native = native_index(review/'segments.rpt')
    native.update(native_index(review/'additional-segments/segments.rpt'))
    native.update(native_index(review/'phase-extra-segments/segments.rpt'))
    original = {r['rtl']: r for r in read('cell-inverted-review-inputs.json')}
    draft = read('corrections-draft.json')
    cell_reviews = read('physical-cell-phase-review.json')
    vendor = (review/'vendor-functions.v').read_text()
    models = {m[1]: m[2].split('specify')[0] for m in re.finditer(
        r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule', vendor)}
    udp = (review/'vendor-udp.v').read_text()

    def literal(ref, primitive, args):
        assert re.search(r'\b'+primitive+r'\s+(?:\w+\s*)?\(\s*'+
                         r'\s*,\s*'.join(map(re.escape,args.split(',')))+r'\s*\)',models[ref]), ref

    def pins(cell):
        return {k: v.strip() for k, v in cells[cell]['pins'].items()}

    def driver(net):
        row, = conn['drivers'][reps.get(net,net)]
        return dict(row,pins=pins(row['cell']))

    def upstream(cell,pin):
        return driver(conn['pins'][cell+'/'+pin])

    def add(rtl, net, inverted, reason, evidence):
        draft['aliases'].append(dict(rtl=rtl, gate=net, inverted=inverted, reason=reason, evidence=evidence))

    udp_set = re.search(r'primitive udp_edffts\b[\s\S]*?endprimitive',udp)[0]
    assert re.search(r'\?\s+r\s+0\s+\?\s+\?\s+\?\s*:\s*\?\s*:\s*0',udp_set)
    assert re.search(r'\?\s+r\s+1\s+0\s+\?\s+\?\s*:\s*\?\s*:\s*1',udp_set)
    core = ROOT/'build/optimization/rtl_sources'/NAME/'encoder/kwt_encoder.sv'
    source = core.read_text()
    assert 'wp_boot?wp_capture_token[6]:input_read_generation' in source
    assert 'capture_value=wp_boot?ap_input_rdata' in source

    for row in specialized:
        if row['kind']=='net_semantics':
            if row['segment'].endswith('/enable_BAR'):
                reviewed = {r['rtl']: r for r in draft['aliases']}
                assert all(reviewed[a['rtl']]['inverted'] and
                           reviewed[a['rtl']]['evidence']['unary_chain'] for a in row['aliases'])
                continue
            assert row['segment']=='shared_memory/memory/en_BAR'
            dr = driver(row['segment'])
            literal(dr['ref'],'nor','ZN,A1,A2')
            host, joined_buffer = (upstream(dr['cell'],pin) for pin in ('A1','A2'))
            literal(host['ref'],'and','Z,A1,A2')
            assert set(host['pins'][k] for k in ('A1','A2'))=={'host_cmd_ready','host_cmd_valid'}
            literal(joined_buffer['ref'],'buf','Z,I')
            joined = upstream(joined_buffer['cell'],'I')
            literal(joined['ref'],'nor','ZN,A1,A2')
            handshake, decode = (upstream(joined['cell'],pin) for pin in ('A1','A2'))
            literal(handshake['ref'],'nand','ZN,A1,A2')
            assert set(handshake['pins'][k] for k in ('A1','A2'))=={'joined_cmd_ready','joined_cmd_valid'}
            literal(decode['ref'],'nand','ZN,A1,A2,A3,A4')
            wrapper=(ROOT/'build/optimization/complete_soc'/NAME/'kwt_shared_dma_icb_sm40.sv').read_text()
            assert '.en(physical_accept)' in wrapper and 'wire host_primary=host_fire&&!host_dual;' in wrapper
            assert 'wire host_dual_candidate=host_stream&&joined_fire&&joined_load_read;' in wrapper
            add(row['aliases'][0]['rtl'],row['aliases'][0]['gate'],True,
                'NOR of host acceptance and address-qualified joined acceptance. The secondary write also implies joined acceptance.',
                dict(driver=dr,host=host,joined=joined,handshake=handshake,decode=decode))
            continue

        rtl, cell, ref = row['rtl'],row['cell'],row['ref']
        signal = rtl.rsplit('/',1)[-1]
        p = pins(cell)
        output = 'QN' if 'QN' in p else 'Q'
        literal(ref, 'not' if output=='QN' else 'buf',output+',n0')
        evidence = dict(cell=cell,ref=ref,pins=p)
        if signal.startswith('jp_input_return[') and ref=='EDQNV6_12TR40':
            bit = int(signal.split('[')[1][:-1])
            assert bit//16%4==0 and p['QN']==signal
            mux = upstream(cell,'D')
            literal(mux['ref'],'udp_mux2','z,I0,I1,S')
            literal(mux['ref'],'not','ZN,z')
            prefix='ap_input_rows_%d__generation_data'% (bit//64)
            assert mux['pins']['I0']==prefix+'[%d]'%(bit%16+16)
            assert mux['pins']['I1']==prefix+'[%d]'%(bit%16)
            selector = upstream(mux['cell'],'S')
            literal(selector['ref'],'not','ZN,I')
            gen = upstream(selector['cell'],'I')
            literal(gen['ref'],'udp_mux2','Z,I0,I1,S')
            assert (gen['pins']['I0'],gen['pins']['I1'])==('wp_capture_token[6]','input_read_generation')
            literal(ref,'udp_edff','n0,D,CK,xRN,xSN,E,NOTIFIER')
            inverted=False
            reason='The negative mux of the two literal input SRAM Q bits feeds D. QN restores the selected positive input.'
            evidence.update(mux=mux,selector=selector,generation=gen)
        elif signal=='jp_input_return[208]' and ref=='DGRSNQNV6_12TR40':
            literal(ref,'udp_edffts','n0,D,clk,xRN,xSN,EN,NOTIFIER')
            d,rn=(upstream(cell,k) for k in ('D','RN'))
            for gate in (d,rn):
                literal(gate['ref'],'and','outA,A2,A1')
                literal(gate['ref'],'and','outB,B2,B1')
                literal(gate['ref'],'nor','ZN,outA,outB')
            assert d['pins']['A1']=='ap_input_rows_3__generation_data[16]'
            assert d['pins']['B2']=='ap_input_rows_3__generation_data[0]'
            assert rn['pins']['A1']==signal and rn['pins']['B2']=='jp_input_return[192]'
            cap = upstream(rn['cell'],'A2')
            literal(cap['ref'],'not','ZN,I')
            assert cap['pins']['I']==p['SN']
            prior_enable=upstream(rn['cell'],'B1')
            literal(prior_enable['ref'],'nor','ZN,A1,A2')
            assert prior_enable['pins']['A1']==cap['pins']['ZN']
            same_gen = [upstream(d['cell'],pin) for pin in ('A2','B1')]
            for term in same_gen:
                literal(term['ref'],'nor','ZN,A1,A2')
            assert same_gen[0]['pins']['A1']=='n48207'
            assert same_gen[1]['pins']['A1']=='n4441'
            for term in same_gen:
                assert term['pins']['A2'] in ('n84','n62017')
            boot = upstream(prior_enable['cell'],'A2')
            literal(boot['ref'],'not','ZN,I')
            assert boot['pins']['I']=='n1769'
            inverted=False
            reason='With capture low, synchronous set/reset holds the prior QN. On capture the reset path supplies the previous tap outside boot, and the complemented selected SRAM bit at D restores positive QN during boot.'
            evidence.update(d=d,rn=rn,capture=cap,previous_tap=prior_enable,generation=same_gen,boot=boot)
        elif signal=='operand_weight[176]' and ref=='EDGRNQV2_12TR40':
            rn=upstream(cell,'RN')
            literal(rn['ref'],'nand','ZN,A1,A2')
            assert p['D']=="1'b1" and rn['pins']['A1']=='pm_rdata[176]' and rn['pins']['A2']==p['E']
            literal(ref,'udp_edfft','n0,D,CK,xRN,xSN,E,NOTIFIER')
            inverted=True
            reason='With capture enabled the reset pin is the complement of the positive SRAM Q. A one resets physical Q to zero and a zero captures D=1.'
            evidence['synchronous_reset']=rn
        elif signal=='owner' and ref=='DRNQNV2_12TR40':
            assert p['RDN']=='rst_n' and cell.endswith('/core_arbiter/owner_reg')
            literal(ref,'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
            mux=upstream(cell,'D')
            literal(mux['ref'],'udp_mux2','z,I0,I1,S')
            literal(mux['ref'],'not','ZN,z')
            enable,grant=(upstream(mux['cell'],pin) for pin in ('S','I0'))
            literal(enable['ref'],'nand','ZN,A1,A2')
            assert {enable['pins']['A1'],enable['pins']['A2']}=={'s_cmd_valid','s_cmd_ready'}
            assert mux['pins']['I1']==p['QN']
            literal(grant['ref'],'not','ZN,I')
            grant_positive=upstream(grant['cell'],'I')
            literal(grant_positive['ref'],'nand','ZN,A1,A2')
            arbiter_source=(core.parent/'kwt_ld_icb_arbiter.sv').read_text()
            assert 'owner<=0;' in arbiter_source and 'owner<=grant;' in arbiter_source
            inverted=True
            reason='Reset-zero internal state with literal QN inversion. The inverted mux selects the negative grant on acceptance and feeds back QN on hold.'
            evidence.update(mux=mux,enable=enable,grant=grant,grant_positive=grant_positive)
        else:
            raise ValueError(row)
        net = original[rtl][output+'_net']
        assert ('pin',cell+'/'+output) in native
        evidence['native_output']=native['pin',cell+'/'+output]
        cell_reviews.append(dict(rtl=rtl,physical_inverted=inverted,output=output,net=net,
                                 reason=reason,evidence=evidence))
        if inverted:
            draft['replace_native_cell_aliases'].append(rtl)
            add(rtl,net,True,reason,evidence)

    prologue = {n:d for n,d in cells.items() if n.startswith('shared_memory/bias_committed_reg_') or
                ('/core/wp_' in n and ('Q' in d['pins'] or 'QN' in d['pins']))}
    for cell,row in prologue.items():
        assert ('pin',cell+'/D') in native
        if 'Q' in row['pins']:
            assert ('pin',cell+'/Q') in native
            literal(row['ref'],'buf','Q,n0')
        else:
            assert ('pin',cell+'/QN') in native
            literal(row['ref'],'not','QN,n0')
    write('prologue-physical-review.json',dict(tag=inv['tag'],pending_resolved=specialized,states=prologue))
    write('corrections-draft.json',draft)
    write('physical-cell-phase-review.json',cell_reviews)
    phase.local_review('assemble')


def retarget_ir_valid():
    _, report, _, review = bind('P2', variant=NAME)
    draft_path = review/'corrections-draft.json'
    draft = json.loads(draft_path.read_text())
    status = json.loads((report/'phase-verdict.json').read_text())
    conn = json.loads((review/'connectivity.json').read_text())
    inv = json.loads((review/'inventory.json').read_text())
    reps = conn['representatives']
    segment, = {reps.get(row['net'],row['net']) for row in status['mismatches']}
    inverter, = conn['drivers'][segment]
    assert inverter['ref']=='INV0_12TR40' and inverter['pin']=='ZN'
    positive = conn['pins'][inverter['cell']+'/I']
    state, = conn['drivers'][reps.get(positive,positive)]
    assert state['cell'].endswith('/ir_valid_dfflr/qout_r_reg_0_') and state['pin']=='Q'
    assert state['ref']=='DRNQV6_12TR40'
    vendor = (review/'vendor-functions.v').read_text()
    model = re.search(r'\bmodule INV0_12TR40\b[\s\S]*?endmodule',vendor)[0]
    assert re.search(r'\bnot\s+\w+\s*\(\s*ZN\s*,\s*I\s*\)',model)
    model = re.search(r'\bmodule DRNQV6_12TR40\b[\s\S]*?endmodule',vendor)[0]
    assert re.search(r'\bbuf\s+\w+\s*\(\s*Q\s*,\s*n0\s*\)',model)
    cell = inv['cells'][state['cell']]['pins']
    assert cell['RDN'].strip()=='rst_n' and cell['Q'].strip()=='qout_0_'
    alias, = [row for row in draft['aliases'] if row['rtl'].endswith('/ir_valid_dfflr/qout[0]')]
    assert alias['inverted'] and reps.get(alias['gate'],alias['gate'])==segment
    backup=review/'analysis-recovery/probe-attempt-02'
    backup.mkdir(parents=True)
    for name in ('corrections-draft.json','phase-expectations.json'):
        shutil.copyfile(review/name,backup/name)
    shutil.copytree(review/'reviewed-draft',backup/'reviewed-draft')
    shutil.copyfile(report/'phase-verdict.json',report/'phase-probe02-verdict.json')
    old=alias.copy()
    alias.update(gate=positive,inverted=False,
                 reason='Source is the reset-zero valid register at positive Q. The literal inverter produces the negative dispatch net.')
    (review/'ir-valid-positive-source.json').write_text(json.dumps(dict(
        old_rule=old,new_rule=alias,driver=state,receiver=inverter,probe=status['attempt']),indent=2)+'\n')
    draft_path.write_text(json.dumps(draft,indent=2)+'\n')
    phase.local_review('assemble')


def annotate_negative_valid():
    _, report, _, review = bind('P2', variant=NAME)
    draft_path=review/'corrections-draft.json'
    draft=json.loads(draft_path.read_text())
    phase_data=json.loads((review/'ir-valid-positive-source.json').read_text())
    source=phase_data['new_rule']['rtl']
    rtl=source.rsplit('/ir_valid_dfflr/',1)[0]+'/u_e203_ifu_litebpu/ir_empty'
    producer=phase_data['receiver']
    assert producer['ref']=='INV0_12TR40' and producer['pin']=='ZN'
    act=json.loads((review/'saif-index.json').read_text())['activity']
    assert (act[rtl]['T0'],act[rtl]['T1'],act[rtl]['TC'])==(act[source]['T1'],act[source]['T0'],act[source]['TC'])
    ifetch=ROOT/'build/server/official_2025/e203_hbirdv2-master/rtl/e203/core/e203_ifu_ifetch.v'
    assert 'wire ir_empty = ~ir_valid_r;' in ifetch.read_text()
    status=json.loads((report/'phase-verdict.json').read_text())
    assert status['attempt']=='probe-attempt-03' and len(status['mismatches'])==4
    assert {row['observed']['SP']['value'] for row in status['mismatches']}=={'0.00251911'}
    backup=review/'analysis-recovery/probe-attempt-03'
    backup.mkdir(parents=True)
    for name in ('corrections-draft.json','phase-expectations.json'):
        shutil.copyfile(review/name,backup/name)
    shutil.copytree(review/'reviewed-draft',backup/'reviewed-draft')
    shutil.copyfile(report/'phase-verdict.json',report/'phase-probe03-verdict.json')
    for key in ('suppressed_opposite_phase_aliases','deduplicated_positive_aliases'):
        draft[key]=[alias for alias in draft[key] if alias!=rtl]
    replacement=dict(rtl=rtl,gate=producer['net'],gate_pin=producer['cell']+'/ZN',inverted=False,
        reason='The explicit RTL ir_empty statistic already has the inverter-output polarity.',
        evidence=dict(positive_raw=act[source],negative_raw=act[rtl],literal_inverter=producer))
    draft['aliases'].append(replacement)
    (review/'ir-valid-negative-source.json').write_text(json.dumps(replacement,indent=2)+'\n')
    draft_path.write_text(json.dumps(draft,indent=2)+'\n')
    phase.local_review('assemble')


if __name__=='__main__':
    action=sys.argv[1] if len(sys.argv)>1 else 'review'
    {'review':main,'retarget-ir-valid':retarget_ir_valid,'negative-valid':annotate_negative_valid}[action]()
