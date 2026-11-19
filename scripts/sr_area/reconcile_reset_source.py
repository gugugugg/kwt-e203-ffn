"""Check the S3 final netlist's active-low PLIC reset after its two inverters."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from assemble_ffn_sr_area_review import assemble
from ffn_sr_area import REPORT, dump

name = 'ffn_sra_S3'
folder = REPORT / 'activity-mapping/native-review-first' / name


def load(leaf):
    return json.loads((folder / leaf).read_text())


rows = load('corrected-injection-collisions.json')
collision, = [row for row in rows if all(s['raw']['T0'] + s['raw']['T1'] > 0 for s in row['sources'])]
driver, = collision['drivers']
stem = driver['cell'].rsplit('/', 1)[0]
cells = load('inventory.json')['cells']
chain = [cells[stem + '/' + cell] for cell in ('U463', 'U3')]
assert collision['segment'].endswith('/dp_gt_0_vld_dfflr/rst_n')
assert [c['ref'] for c in chain] == ['CLKINV12_12TR40', 'CLKINV12_12TR40']
assert [c['pins'] for c in chain] == [dict(I='rst_n', ZN='n363'), dict(I='n363', ZN='n346')]
assert cells[stem + '/source_gen_1__u_LevelGateway_1_1']['pins']['reset_BAR'] == 'n346'
draft = load('corrections-draft.json')
positive = {s['rtl'] for s in collision['sources'] if s['rtl'].endswith('/rst_n')}
for rule in draft['aliases']:
    if rule['rtl'] in positive:
        rule.update(inverted=False, reason='Actual U463/U3 double inversion preserves rst_n.')
dump(folder / 'before-physical-reset-reconciliation.json', collision)
dump(folder / 'corrections-draft.json', draft)
dump(folder / 'physical-reset-reconciliation.json',
     dict(chain=chain, positive_rtl=sorted(positive), original_map_and_SAIF_unchanged=True))
assemble(name)
