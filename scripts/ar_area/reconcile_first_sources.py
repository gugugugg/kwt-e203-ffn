"""Close SS reset phase and resolve the FIFO source representation collision."""
from pathlib import Path
import json
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from assemble_ffn_ar_area_review import assemble
from ffn_ar_area import REPORT, dump

FOLDER = REPORT/'activity-mapping/native-review-first'


def read(path):
    return json.loads(path.read_text())


def reconcile():
    name = 'ffn_ara_SS'
    folder = FOLDER/name
    draft = read(folder/'corrections-draft.json')
    conn = read(folder/'connectivity.json')
    cells = read(folder/'inventory.json')['cells']
    groups = read(folder/'corrected-injection-collisions.json')
    finite = [r for r in groups if all(s['raw']['T0']+s['raw']['T1']>0 for s in r['sources'])]
    assert len(finite)==2
    reset = next(r for r in finite if r['segment'].endswith('/dp_gt_0_vld_dfflr/rst_n'))
    plic = reset['segment'].split('/flop_icb_rsp')[0]
    chain = [cells[plic+'/'+leaf] for leaf in ('U2','U464','U463')]
    assert [c['ref'] for c in chain]==['CLKBUFV6_12TR40','CLKINV12_12TR40','CLKINV12_12TR40']
    assert [c['pins'] for c in chain]==[dict(I='rst_n',Z='n2'),dict(I='n2',ZN='n343'),dict(I='n343',ZN='n342')]
    assert cells[plic+'/source_gen_1__u_LevelGateway_1_1']['pins']['reset_BAR']=='n342'
    positive = {s['rtl'] for s in reset['sources'] if s['rtl'].endswith('/rst_n')}
    for rule in draft['aliases']:
        if rule['rtl'] in positive:
            rule.update(inverted=False,reason='Actual U2 buffer and U464/U463 double inversion deliver positive rst_n; LevelGateway reset_BAR is the same negative reset.')
    fifo = next(r for r in finite if r['segment'].endswith('/i_icb_cmd_valid_BAR'))
    driver = fifo['drivers'][0]
    assert driver['ref']=='CLKINV0_12TR40' and cells[driver['cell']]['pins']==dict(I='qout_0_',ZN='qout_0__BAR')
    input_net = conn['pins'][driver['cell']+'/I']
    q = conn['drivers'][conn['representatives'].get(input_net,input_net)][0]
    assert q['ref']=='DRNQV6_12TR40' and q['pin']=='Q'
    # Keep the primary inverted FF source. The downstream ready aliases round their
    # sampled duration by one simulator time unit and refer to the same physical net.
    duplicates = [s['rtl'] for s in fifo['sources'] if s['rtl'].endswith(('/o_icb_cmd_ready','/i_icb_cmd_ready','/i_rdy'))]
    assert len(duplicates)==3 and any(s['rtl'].endswith('/qout[0]') and s['inverted'] for s in fifo['sources'])
    draft['deduplicated_positive_aliases'] = sorted(duplicates)
    dump(folder/'corrections-draft.json',draft)
    dump(folder/'first-physical-source-resolution.json',dict(reset_chain=chain,reset_aliases=len(positive),
         fifo_driver=driver,fifo_positive_register=q,removed_duplicate_ready_aliases=duplicates,
         original_SAIF_preserved=True))
    assemble(name)
    for name in ('ffn_ara_SS','ffn_ara_SR'):
        path = FOLDER/name
        collisions = read(path/'corrected-injection-collisions.json')
        assert all(any(s['raw']['T0']+s['raw']['T1']==0 for s in r['sources']) for r in collisions)
        dump(path/'injection-source-ambiguities.json',dict(audited_ambiguous_groups=[],unknown_alias_groups=collisions,original_SAIF_unchanged=True))


if __name__=='__main__':
    reconcile()
