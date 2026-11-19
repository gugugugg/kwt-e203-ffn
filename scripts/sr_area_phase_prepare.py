"""Prepare actual mixed-port and encoded-memory evidence for a final's phase review."""
from pathlib import Path
import argparse,json,re
from ffn_sr_area import ROOT,REPORT,dump,review_group

def prepare(name):
    out=REPORT/'activity-mapping'/('native-review-'+review_group(name))/name
    inv=json.loads((out/'inventory.json').read_text());conn=json.loads((out/'connectivity.json').read_text())
    groups=[dict(segment=key,aliases=rows,drivers=conn['drivers'].get(key,[]))
            for key,rows in conn['aliases'].items() if any('BAR' in r['gate'] for r in rows)]
    dump(out/'bar-segment-review-inputs.json',groups)
    old={(r['kind'],r['name']) for r in json.loads((out/'query-targets.json').read_text())};targets=[]
    def add(kind,value):
        if (kind,value) not in old:old.add((kind,value));targets.append(dict(kind=kind,name=value))
    for group in groups:
        for row in group['aliases']:add('net',row['gate'])
    for row in json.loads((out/'cell-inverted-review-inputs.json').read_text()):
        for driver in row.get('D_drivers',[]):
            for pin in inv['cells'][driver['cell']]['pins']:
                add('pin',driver['cell']+'/'+pin)
    weight_macros=[]
    for path,cell in inv['cells'].items():
        if cell['ref']=='RAMSP1024X16' and '/core/' in path and 'weight' in path:
            weight_macros.append(dict(cell=path,**cell))
            for stem,count in [('D',16),('Q',16),('WEN',16),('A',10)]:
                for bit in range(count):add('pin',path+'/'+stem+'[%d]'%bit)
            for pin in ['CLK','CEN','GWEN']:add('pin',path+'/'+pin)
    dump(out/'weight-macros.json',weight_macros)
    folder=out/'additional-segments';folder.mkdir(exist_ok=True)
    dump(folder/'targets.json',targets)
    print(name,'actual_BAR_segments',len(groups),'weight_macros',len(weight_macros),'additional_targets',len(targets),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('variants',nargs='+')
    for name in parser.parse_args().variants:prepare(name)
