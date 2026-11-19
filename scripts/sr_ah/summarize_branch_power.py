"""Summarize the AH branch using the native E archive and accepted SR reports."""
import json
from pathlib import Path

from prepare import ROOT, REPORT, dump


def main():
    source=REPORT/'received/eco3-full/native-evidence'
    native=source/REPORT.relative_to(ROOT)
    tag='opt_ffn_sr_ah_eco3_final_ss_ema2'
    selected=json.loads((native/'eco3-final-selection.json').read_text())
    parent=json.loads((ROOT/'reports/submission/ara-SR-release-20261105/completion.json').read_text())
    measurements=selected['metrics']['measurements']
    cycles=sum(row['cycles'] for row in measurements)
    if len(measurements)!=12 or cycles!=selected['metrics']['cycles'] or cycles!=sum(parent['cycles']):
        raise RuntimeError('AH and SR task windows differ')
    groups={}
    design={}
    for row in measurements:
        for name, root, profile in [('AH',source,tag),('SR',ROOT,parent['implementation_tag'])]:
            report=root/'reports/server'/('complete_soc_sm40_'+profile)/('power_%d'%row['case'])
            modules=json.loads((report/'power_groups.json').read_text())
            values=json.loads((report/'power_values.json').read_text())
            if modules['unit']!='W' or values['unit']!='W':
                raise RuntimeError('Native power source unit differs')
            weight=row['cycles']/cycles
            for field in ('total_w','internal_w','switching_w','leakage_w'):
                design.setdefault(field,{}).setdefault(name,0.0)
                design[field][name]+=values[field]*weight
            for key, data in modules['groups'].items():
                groups.setdefault(key,{}).setdefault(name,0.0)
                groups[key][name]+=sum(data[k] for k in ('internal_w','switching_w','leakage_w'))*weight
    for table in (design,groups):
        for values in table.values():
            values['delta_w']=values['AH']-values['SR']
    dump(REPORT/'eco3-power-attribution.json',dict(method='Cycle-weighted native SoC and leaf-group attributes',
         design=design,groups=groups,unseparated_group='accelerator_other'))
    print('AH_POWER_ATTRIBUTION', sorted(((k, v['delta_w']*1000) for k,v in groups.items()),
                                         key=lambda item: -abs(item[1]))[:6])


if __name__=='__main__':
    main()
