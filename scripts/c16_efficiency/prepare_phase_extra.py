import json
import re
from prepare import REPORT

out=REPORT/'activity-mapping/native-review-W/ffn_ce_W'
inv=json.loads((out/'inventory.json').read_text())
old={(r['kind'],r['name']) for r in json.loads((out/'query-targets.json').read_text())}
old.update((r['kind'],r['name']) for r in json.loads((out/'additional-segments/targets.json').read_text()))
targets=[]
def add(kind,name):
    if (kind,name) not in old:old.add((kind,name));targets.append(dict(kind=kind,name=name))
for r in inv['mappings']:
    if not r['cell'] and r['rtl'].startswith('shared_memory/') and re.search(r'held_|live_|physical_|owner|active|grant|recipient|available|handoff|pending|prefer|to_host',r['rtl']):
        add('net',r['gate'])
for name,cell in inv['cells'].items():
    if name.startswith('shared_memory/') and re.search(r'held_|owner|active|pending|prefer|to_host|joined_rsp',name):
        for pin in ['D','Q','QN','RDN','SDN']:
            if pin in cell['pins']:add('pin',name+'/'+pin)
for stem,bits in [('en',None),('we',None),('addr',17),('wdata',32),('wmask',4)]:
    for name in [stem] if bits is None else [stem+'[%d]'%i for i in range(bits)]:
        add('net','shared_memory/memory/'+name)
folder=out/'phase-extra-segments';folder.mkdir(exist_ok=True)
(folder/'targets.json').write_text(json.dumps(targets,indent=2))
(REPORT/'c16-efficiency-extra-targets.json').write_text(json.dumps(targets,indent=2))
print('EFFICIENCY_EXTRA_TARGETS',len(targets),flush=True)
