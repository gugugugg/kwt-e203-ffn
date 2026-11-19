"""Check the actual post-update case-one annotations without changing any activity."""
import json,re,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_final_energy import REPORT,dump

def records(path):
    result=[];row=None
    for line in path.read_text().splitlines():
        if line.startswith('NET '):row=dict(net=line[4:]);result.append(row)
        elif line.startswith(('SP ','TR ')):
            m=re.match(r'(SP|TR)\s+\{\s*"[^"]+"\s+(\S+)\s+(\S+)\s*\}',line)
            if m:row[m.group(1)]=dict(value=m.group(2),source=m.group(3))
    return result

def main():
    result=[]
    for name in ['ffn_cfe_SS','ffn_cfe_O1']:
        own=REPORT/'activity-mapping/native-review-first'/name;draft=json.loads((own/'reviewed-draft'/(name+'.json')).read_text());expect=json.loads((own/'phase-expectations.json').read_text());tag=draft['tag']
        folder=ROOT/'reports/server'/('complete_soc_sm40_'+tag)/'power_1';rows=records(folder/'activity-phase-review.rpt');assert len(rows)==len(draft['probe_nets'])
        errors=[];numeric=0;unknown=[];sources=Counter()
        for net,row in zip(draft['probe_nets'],rows):
            sources.update(row[k]['source'] for k in ['SP','TR'])
            entry=expect['nets'].get(net);values=[s['expected'] for s in entry['sources'] if s['expected'] is not None] if entry else []
            if not values:unknown.append(row);continue
            numeric+=1
            for key in ['SP','TR']:
                wanted={v[key] for v in values}
                if len(wanted)!=1 or row[key]['value'] not in wanted:errors.append(dict(net=net,attribute=key,observed=row[key],expected=sorted(wanted)))
        logs=[]
        for case in range(1,24,2):
            path=ROOT/'reports/optimization/complete_soc'/name/('power_%02d_all.log'%case);text=path.read_text();errs=re.findall(r'^Error:.*$',text,re.M)
            done='XPIAN_ENCODER_POWER_DONE' in text and 'XPIAN_POWER_PRECISE_EXPORT=1' in text and 'XPIAN_ACTIVITY_VERIFIED_CORRECTION_APPLIED=1' in text
            logs.append(dict(case=case,Error_count=len(errs),complete_markers=done))
            if errs or not done:errors.append(dict(case=case,errors=errs,complete_markers=done))
        value=dict(variant=name,tag=tag,passed=not errors,known_nets=numeric,exact_SP_TR_comparisons=2*numeric,unknown_before_update_power=len(unknown),post_update_sources=dict(sources),unknowns_not_zero_filled=True,errors=errors,power12_logs=logs,power_or_SAIF_recomputed=False)
        dump(own/'formal-power-case1-review.json',value);dump(own/'formal-power-propagated-unknowns.json',unknown);result.append(value)
    dump(REPORT/'normal-power-activity-review.json',dict(passed=all(x['passed'] for x in result),candidates=result));print(json.dumps([dict(variant=x['variant'],passed=x['passed'],comparisons=x['exact_SP_TR_comparisons'],errors=len(x['errors'])) for x in result]),flush=True)
    if not all(x['passed'] for x in result):raise RuntimeError('Read actual normal-power annotations')

if __name__=='__main__':main()
