"""Review already computed normal-power activity against the passed case-one probe."""
from pathlib import Path
from collections import Counter
import json,re,sys
ROOT=Path(__file__).resolve().parents[2];REPORT=ROOT/'reports/optimization/ffn_sr_area'

def records(path):
    result=[];row=None
    for line in path.read_text().splitlines():
        if line.startswith('NET '):
            row={'net':line[4:]};result.append(row)
        elif line.startswith(('SP ','TR ')):
            m=re.match(r'(SP|TR)\s+\{\s*"[^"]+"\s+(\S+)\s+(\S+)\s*\}',line)
            if m:row[m.group(1)]={'value':m.group(2),'source':m.group(3)}
    return result

def main():
    results=[]
    for name in ['ffn_sra_SS','ffn_sra_S3']:
        state=json.loads((REPORT/(name+'.json')).read_text());tag=json.loads((ROOT/state['profile']).read_text())['tag']
        own=REPORT/'activity-mapping/native-review-first'/name
        correction=(REPORT/'activity-mapping'/(name+'.tcl')).read_bytes()
        verdicts=sorted(own.glob('probe-attempt-*/comparison-verdict.json'))
        probe=next((p.parent for p in reversed(verdicts)
                    if json.loads(p.read_text())['passed']
                    and (p.parent/'correction-used.tcl').read_bytes()==correction),None)
        if probe is None:raise RuntimeError('No passed probe uses the normal-power correction '+name)
        old=records(probe/'activity-phase-review.rpt')
        path=ROOT/'reports/server'/('complete_soc_sm40_'+tag)/'power_1/activity-phase-review.rpt'
        new=records(path)
        if len(old)!=len(new) or any(a['net']!=b['net'] for a,b in zip(old,new)):raise RuntimeError('Actual normal-power query order differs '+name)
        counts=Counter();changes=[];unknown=[]
        for a,b in zip(old,new):
            for key in ['SP','TR']:
                before=a[key];after=b[key];counts['post_'+after['source']]+=1
                if before['value']=='-1' or before['source']=='UNINITIALIZED':
                    counts['original_unknown_attributes']+=1
                    if after['value']!='-1' and after['source']!='UNINITIALIZED':counts['unknown_now_resolved_attributes']+=1
                    else:unknown.append({'net':a['net'],'attribute':key,'observed':after})
                elif before['value']!=after['value']:
                    changes.append({'net':a['net'],'attribute':key,'before':before,'after':after})
                else:counts['preserved_numeric_attributes']+=1
        log=ROOT/'reports/optimization/complete_soc'/name/'power_01_all.log';text=log.read_text(errors='replace')
        errors=[line for line in text.splitlines() if line.startswith('Error:')]
        value={'variant':name,'tag':tag,'normal_power_complete':'XPIAN_ENCODER_POWER_DONE' in text,'normal_errors':errors,'counts':dict(counts),'known_value_changes':changes,'remaining_unknown':unknown,'power_recomputed':False,'unknown_zero_filled':False,'report':path.relative_to(ROOT).as_posix()}
        value['passed']=value['normal_power_complete'] and not errors and not changes
        results.append(value)
    out={'passed':all(v['passed'] for v in results),'candidates':results,'source_reports_unchanged':True,'new_CPU_or_EDA_executed':False}
    (REPORT/'normal-power-activity-review.json').write_text(json.dumps(out,indent=2))
    print(json.dumps({**out,'candidates':[{k:v for k,v in r.items() if k!='remaining_unknown'} for r in results]},indent=2))
    return 0 if out['passed'] else 1
if __name__=='__main__':sys.exit(main())
