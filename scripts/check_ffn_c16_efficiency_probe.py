"""Compare literal native SP/TR text with the own-SAIF, reviewed-encoding expectations."""
from pathlib import Path
from collections import Counter
import argparse,json,re
from ffn_c16_efficiency import REPORT,dump,review_group

def check(name,attempt):
    out=REPORT/'activity-mapping'/('native-review-'+review_group(name))/name;folder=out/('probe-attempt-%02d'%attempt)
    result=json.loads((folder/'result.json').read_text());draft=json.loads((out/'reviewed-draft'/(name+'.json')).read_text())
    expectations=json.loads((out/'phase-expectations.json').read_text());records=[];row=None
    for line in (folder/'activity-phase-review.rpt').read_text().splitlines():
        if line.startswith('NET '):row=dict(reported_net=line[4:]);records.append(row)
        elif line.startswith(('SP ','TR ')):
            m=re.match(r'(SP|TR)\s+\{\s*"[^"]+"\s+(\S+)\s+(\S+)\s*\}',line)
            if m:row[m.group(1)]=dict(value=m.group(2),source=m.group(3))
    errors=[];numeric=0;unknown=[];source_counts=Counter()
    if len(records)!=len(draft['probe_nets']):errors.append(dict(reason='actual record count',actual=len(records),expected=len(draft['probe_nets'])))
    for net,observed in zip(draft['probe_nets'],records):
        observed['requested_net']=net;source_counts.update(observed[k]['source'] for k in ['SP','TR'] if k in observed)
        entry=expectations['nets'].get(net)
        values=[s['expected'] for s in entry['sources'] if s['expected'] is not None] if entry else []
        if not values:unknown.append(observed);continue
        for key in ['SP','TR']:
            wanted={v[key] for v in values};actual=observed.get(key,{}).get('value')
            if len(wanted)!=1 or actual not in wanted:errors.append(dict(net=net,attribute=key,actual=actual,expected=sorted(wanted),sources=entry['sources']))
        numeric+=1
    passed=result['native_execution_complete'] and not result['errors'] and not errors and result['original_inputs_archive_byte_identical'] and not result['update_power_called']
    verdict=dict(variant=name,tag=result['tag'],attempt=attempt,passed=passed,native_errors=result['errors'],queried_records=len(records),numeric_nets=numeric,
        numeric_comparisons=2*numeric,source_counts=dict(source_counts),unknown_or_unresolved_nets=len(unknown),unknown_values_preserved=True,zero_filled=False,
        duration=expectations['duration'],duration_binary32=expectations['duration_binary32'],comparison='native .6g text; binary32 injection and each literal inverter propagation retained separately',
        errors=errors,original_saif_unchanged=True,power_recomputed=False)
    dump(folder/'comparison-verdict.json',verdict);dump(folder/'observed-activity.json',records);dump(folder/'unresolved-activity-preserved.json',unknown)
    print(name,'attempt',attempt,'passed',passed,'numeric',numeric,'unknown',len(unknown),'mismatches',len(errors),flush=True)
    if errors:print(json.dumps(errors[:2]),flush=True)
    return verdict

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',type=int,required=True);parser.add_argument('variants',nargs='+');args=parser.parse_args()
    verdicts=[check(name,args.attempt) for name in args.variants]
    raise SystemExit(0 if all(v['passed'] for v in verdicts) else 1)
