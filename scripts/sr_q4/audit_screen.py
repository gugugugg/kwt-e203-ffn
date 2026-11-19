"""Verify Q4 screening attribution and the exact scope of the native size-only batch."""
import json
import re
from prepare import ROOT, REPORT, dump


def clean_netlist(tag):
    file=ROOT_RECEIVED/'build/server'/('complete_soc_sm40_'+tag)/'netlist.v'
    return re.sub(r'/\*.*?\*/|//[^\r\n]*','',file.read_text(),flags=re.S)


def counts(path):
    category=None
    result={}
    for line in path.read_text().splitlines():
        if re.match(r'^   (max_|min_|clock_|recovery|removal)',line):
            category=line.strip()
        if '(VIOLATED)' in line:
            result[category]=result.get(category,0)+1
    return result


ROOT_RECEIVED=REPORT/'received/screen/native-evidence'
NATIVE_REPORT=ROOT_RECEIVED/REPORT.relative_to(ROOT)


def main():
    screen=json.loads((NATIVE_REPORT/'selected-screen.json').read_text())
    plan=json.loads((NATIVE_REPORT/'eco/eco1/planned-sizes.json').read_text())
    previous=clean_netlist(plan['previous'])
    current=clean_netlist(plan['current'])
    core,=[m for m in re.finditer(r'(?ms)^module\s+\S+.*?^endmodule',previous)
           if 'jp_input_return_reg_' in m[0] and 'accumulator_reg_' in m[0]]
    rewritten=core[0]
    for row in plan['rows']:
        name=row['cell'].rsplit('/',1)[1]
        pattern=r'(?m)(^\s*)'+row['old']+r'(\s+'+name+r'\s*\()'
        rewritten,n=re.subn(pattern,r'\g<1>'+row['new']+r'\g<2>',rewritten)
        if n!=1:
            raise RuntimeError('Cannot match changed cell in Q4 predecessor: '+name)
    adjusted=previous[:core.start()]+rewritten+previous[core.end():]
    if re.sub(r'\s+','',adjusted)!=re.sub(r'\s+','',current):
        raise RuntimeError('Q4 post-ECO netlist differs beyond selected cell references')
    old=json.loads((NATIVE_REPORT/'final-screen.json').read_text())
    eco=NATIVE_REPORT/'eco'
    records=dict(size_only_verified=True,sized_cells=len(plan['rows']),native_screen_passed=screen['passed'],
                 baseline_electrical=counts(eco/'baseline/constraints.rpt'),
                 eco_electrical=counts(eco/'eco1/constraints.rpt'),
                 original_setup_ns=old['checks']['timing_max']['minimum_reported_slack_ns'],
                 eco_setup_ns=screen['checks']['timing_max']['min_ns'])
    dump(REPORT/'screen-audit.json',records)
    print(json.dumps(records,indent=2))


if __name__=='__main__':
    main()
