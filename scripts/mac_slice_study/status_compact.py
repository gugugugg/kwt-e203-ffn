from pathlib import Path
import json

r=Path('reports/optimization/ffn_mac_slice_study')
for v in ['REF','SHARE4']:
    p=r/'native'/v/'state.json'
    if p.exists():
        state=json.loads(p.read_text())
        print('SLICE_STATE',v,json.dumps({k:state.get(k) for k in ['area_um2','setup_ns','hold_ns','timing_passed','mapped_formal']}),flush=True)
    p=r/'native'/v/'mapped-formal.log'
    if p.exists():print('SLICE_MAPPED_PROGRESS',v,'\n'.join(p.read_text(errors='replace').splitlines()[-4:]),flush=True)
for name in ['native-recovery.log','native/formal/result.json','native-result.json']:
    p=r/name
    if p.exists():print('SLICE_PROGRESS',name,'\n'.join(p.read_text(errors='replace').splitlines()[-5:]),flush=True)
