"""Rebuild phase evidence from the received native netlist and candidate SAIF."""
import json
from collections import Counter
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'scripts/server')]
import ffn_sr_area as area


def verify_probe(name, report, review, attempt):
    from sr_area.review_normal_power import records
    prefix = report.relative_to(ROOT) / 'activity-mapping/native-review-next' / name
    probe = report / 'received' / attempt / 'native-evidence' / prefix / attempt
    status = json.loads((probe / 'result.json').read_text())
    planned = json.loads((review / 'reviewed-draft' / (name + '.json')).read_text())
    expectations = json.loads((review / 'phase-expectations.json').read_text())['nets']
    representatives = json.loads((review / 'connectivity.json').read_text())['representatives']
    rows = records(probe / 'activity-phase-review.rpt')
    order = planned['probe_nets']
    if (not status['native_execution_complete'] or status['tag'] != planned['tag']
            or len(rows) != len(order)):
        raise RuntimeError('Native probe and planned phase evidence differ')
    counts = Counter()
    mismatches = []
    for net, row in zip(order, rows):
        observed = row['net']
        if representatives.get(net, net) != representatives.get(observed, observed):
            raise RuntimeError('Native probe name crosses segments: ' + net)
        sources = expectations.get(net, {}).get('sources', [])
        expected = {tuple(item['expected'][key] for key in ('SP', 'TR'))
                    for item in sources if item['expected'] is not None}
        counts.update(row[key]['source'] for key in ('SP', 'TR'))
        if not expected:
            counts['without_independent_expectation'] += 1
        elif tuple(row[key]['value'] for key in ('SP', 'TR')) in expected:
            counts['exact_known_net'] += 1
        else:
            mismatches.append(dict(net=net, observed=row, expected=sorted(expected)))
    verdict = dict(variant=name, tag=status['tag'], attempt=attempt, passed=not mismatches,
                   counts=dict(counts), mismatches=mismatches, unknown_zero_filled=False)
    (report / 'phase-verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
    print(json.dumps(verdict, indent=2), flush=True)


def main(name,mode,attempt='probe-attempt-01'):
    label={'ffn_sr_bidir':'ffn_sr_transport_next','ffn_sr_r3o':'ffn_sr_r3o'}[name]
    report=ROOT/'reports/optimization'/label
    archive=report/'received/inputs/native-evidence'
    area.ROOT=archive
    area.REPORT=archive/report.relative_to(ROOT)
    area.review_group=lambda _:'next'
    from sr_area_phase_inventory import inventory
    from sr_area_phase_connectivity import analyze
    from sr_area_phase_prepare import prepare
    from sr_area_phase_review import review
    from assemble_ffn_sr_area_review import assemble
    if mode=='inspect':
        inventory(name)
        if name=='ffn_sr_r3o':
            from native_activity import stage_registers
            stage_registers(area.REPORT / 'activity-mapping/native-review-next' / name)
        analyze(name)
        prepare(name)
        review(name)
    elif mode=='assemble':
        assemble(name)
    elif mode=='verify':
        verify_probe(name, report, area.REPORT / 'activity-mapping/native-review-next' / name,
                     attempt)

if __name__=='__main__':
    main(*sys.argv[1:])
