"""Use the real ready-port sample for the SS FIFO negative branch."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from assemble_ffn_ar_area_review import assemble
from ffn_ar_area import REPORT, dump

folder = REPORT / 'activity-mapping/native-review-first/ffn_ara_SS'
draft_path = folder / 'corrections-draft.json'
draft = json.loads(draft_path.read_text())
conn = json.loads((folder / 'connectivity.json').read_text())
before = folder / 'analysis-recovery/probe02-ready-branch'
for source in [draft_path, folder / 'phase-expectations.json',
               *sorted((folder / 'reviewed-draft').glob('*'))]:
    target = before / source.relative_to(folder)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source), str(target))
errors = json.loads((folder / 'probe-attempt-02/comparison-verdict.json').read_text())['errors']
ready = json.loads((folder / 'first-physical-source-resolution.json').read_text())['removed_duplicate_ready_aliases']
segments = {conn['representatives'][row['net']] for row in errors}
assert len(errors) == 3 and len(segments) == 1
segment, = segments
assert all(conn['representatives'][rtl] == segment for rtl in ready)
draft['deduplicated_positive_aliases'] = sorted(set(draft['deduplicated_positive_aliases']) - set(ready))
dump(draft_path, draft)
assemble('ffn_ara_SS')
expectations = json.loads((folder / 'phase-expectations.json').read_text())['nets']
for row in errors:
    expectation = expectations[row['net']]
    assert expectation['source'] == 'file'
    assert {s['rtl'] for s in expectation['sources']} == set(ready)
    assert {s['expected']['SP'] for s in expectation['sources']} == {row['actual']}
dump(folder / 'probe02-ready-source-review.json', dict(
    segment=segment, positive_Q_separately_mapped=True, ready_ports=ready,
    reason='Actual inverter output is also the directly sampled ready port. Its SAIF duration is 2846/655707 instead of the one-time-unit shifted complement of Q. Preserve both physical samples.',
    previous_probe_mismatches=errors, manual_values_added=False, original_SAIF_unchanged=True))
