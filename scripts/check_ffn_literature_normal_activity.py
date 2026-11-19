"""Compare existing post-power reports with each final netlist's reviewed SAIF probe."""
from pathlib import Path
from collections import Counter
import json,re,sys
from ffn_literature_power import ROOT,REPORT,dump,review_group

def records(path):
    rows=[];row=None
    for line in path.read_text().splitlines():
        if line.startswith('NET '):row=dict(net=line[4:]);rows.append(row)
        elif line.startswith(('SP ','TR ')):
            m=re.match(r'(SP|TR)\s+\{\s*"[^"]+"\s+(\S+)\s+(\S+)\s*\}',line)
            if m:row[m.group(1)]=dict(value=m.group(2),source=m.group(3))
    return rows

def check(name,attempt):
    folder=REPORT/'activity-mapping'/('native-review-'+review_group(name))/name
    state=json.loads((REPORT/(name+'.json')).read_text())
    profile=json.loads((ROOT/state['profile']).read_text());tag=profile['tag']
    original=records(folder/('probe-attempt-%02d'%attempt)/'activity-phase-review.rpt')
    base=ROOT/'reports/server'/('complete_soc_sm40_'+tag)/'power_1'
    normal=records(base/'activity-phase-review.rpt')
    errors=[];known=0;propagated=0;still_unknown=0;sources=Counter()
    if len(original)!=len(normal):errors.append(dict(reason='record count',probe=len(original),normal=len(normal)))
    for before,after in zip(original,normal):
        if before['net']!=after['net']:errors.append(dict(reason='net identity',probe=before['net'],normal=after['net']))
        unknown=any(before[k]['source']=='UNINITIALIZED' for k in ['SP','TR'])
        if unknown:
            propagated+=all(after[k]['source']=='propagated' for k in ['SP','TR'])
            still_unknown+=any(after[k]['source']=='UNINITIALIZED' for k in ['SP','TR'])
        else:
            known+=1
            for k in ['SP','TR']:
                if before[k]['value']!=after[k]['value']:errors.append(dict(net=after['net'],attribute=k,probe=before[k],normal=after[k]))
        sources.update(after[k]['source'] for k in ['SP','TR'])
    context=json.loads((base/'area_power_context.json').read_text())
    passed=state['formal_passed'] and context['tag']==tag and not errors
    result=dict(variant=name,tag=tag,case=1,passed=passed,known_numeric_nets=known,
        previous_unresolved_now_propagated=propagated,previous_unresolved_still_unknown=still_unknown,
        formal_uninitialized_attributes=sources['UNINITIALIZED'],source_counts=dict(sources),
        zero_filled=False,power_recomputed=False,errors=errors)
    dump(folder/'normal-power-case1-review.json',result)
    print(json.dumps(result),flush=True)
    return passed

if __name__=='__main__':raise SystemExit(0 if check(sys.argv[1],int(sys.argv[2])) else 1)
