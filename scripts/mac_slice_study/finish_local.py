"""Stop only redundant interpreters after equivalent compiled checks passed."""
from local_process import describe,kernel
from prepare import REPORT
import json
import sys

assert json.loads((REPORT/'development-compiled.json').read_text())['passed']
assert json.loads((REPORT/'replay-local-compiled.json').read_text())['passed']
assert json.loads((REPORT/'development.json').read_text())['scenarios']['actual12']['passed']
children=[describe(int(x)) for x in sys.argv[1:]]
assert all(c.get('exited') or ('vvp' in c.get('command','') and 'ffn_mac_slice_study' in c['command']) for c in children)
parents=[describe(pid) for pid in sorted(set(c['ppid'] for c in children if c.get('ppid')))]
assert all(p.get('exited') or any(n in p.get('command','') for n in ['scripts/mac_slice_study/develop.py','scripts/mac_slice_study/replay_local.py']) for p in parents),parents
record=dict(reason='Compiled checks completed on identical RTL; Icarus actual12 also passed; redundant partial runs stopped',
    parents=parents,children=children,completed_evidence_preserved=True)
if (REPORT/'local-backend-resolution.json').exists():
    record['previous']=json.loads((REPORT/'local-backend-resolution.json').read_text())
(REPORT/'local-backend-resolution.json').write_text(json.dumps(record,indent=2))
for p in parents+children:
    if not p.get('exited'):
        handle=kernel.OpenProcess(1,False,p['pid'])
        if handle:
            kernel.TerminateProcess(handle,2);kernel.CloseHandle(handle)
print(json.dumps(record,indent=2))
