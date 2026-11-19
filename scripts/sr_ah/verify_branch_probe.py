"""Compare AH's read-only native SP/TR with its actual SAIF and reviewed phases."""
from collections import Counter
import json
import sys

from review_branch_local import NAME, REPORT, SOURCE, area
from sr_area.review_normal_power import records

REL = area.REPORT.relative_to(SOURCE)/'activity-mapping/native-review-branch'/NAME


def main():
    attempt = sys.argv[1] if len(sys.argv)>1 else '01'
    mode = 'eco3-probe2' if attempt=='02' else 'eco3-probe'
    root = REPORT/'received'/mode/'native-evidence'/REL/('probe-attempt-'+attempt)
    results = json.loads((root/'result.json').read_text())
    review = SOURCE/REL
    expect = json.loads((review/'phase-expectations.json').read_text())
    rows = records(root/'activity-phase-review.rpt')
    representatives=json.loads((review/'connectivity.json').read_text())['representatives']
    planned = json.loads((review/'reviewed-draft'/(NAME+'.json')).read_text())
    ordered = sorted(planned['probe_nets']) if attempt=='02' else planned['probe_nets']
    if (len(rows)!=len(ordered)
            or results['tag']!=planned['tag'] or not results['native_execution_complete']):
        raise RuntimeError('AH probe result does not cover the planned actual nets')
    counts = Counter()
    mismatch = []
    aliases=[]
    for name,row in zip(ordered,rows):
        if name!=row['net']:
            if representatives.get(name,name)!=representatives.get(row['net'],row['net']):
                raise RuntimeError('AH native canonical name crosses segments: '+name)
            aliases.append([name,row['net']])
        keys = ('SP','TR')
        for key in keys:
            counts[row[key]['source']]+=1
        expectation = expect['nets'].get(name)
        if expectation is None:
            continue
        predicted = {tuple(s['expected'][key] for key in keys)
                     for s in expectation['sources'] if s['expected'] is not None}
        if not predicted:
            counts['no_known_saif_state']+=1
            continue
        observed = tuple(row[key]['value'] for key in keys)
        if observed in predicted:
            counts['exact_known_net']+=1
        else:
            mismatch.append(dict(net=name,observed=row,expected=sorted(predicted),
                                 expectation=expectation['source']))
    report = dict(passed=not mismatch,tag=results['tag'],counts=dict(counts),
                  expected_nets=len(expect['nets']),probed_nets=len(rows),
                  mismatches=mismatch,canonical_aliases=aliases,unknown_zero_filled=False)
    path=REPORT/'eco3-phase-verdict.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(report,mismatches=mismatch[:4]),indent=2),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    sys.exit(main())

