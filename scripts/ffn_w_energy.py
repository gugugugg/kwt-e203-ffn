"""Independent W-energy candidates and their fixed complete-task objective."""
from pathlib import Path
import json,shutil
from ffn_residual import prove_bias32,prove_zero_schedule
ROOT=Path(__file__).resolve().parents[1];REPORT=ROOT/'reports/optimization/ffn_w_energy';BUILD=ROOT/'build/optimization/ffn_w_energy'
MANIFESTS=ROOT/'constraints/ffn_w_energy/candidates';AREA_LIMIT=.2764843225;ENERGY_LIMIT_J=1.822518977709749e-05;THROUGHPUT_MIN=1000
def dump(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2))
def load(name):return json.loads((MANIFESTS/(name+'.json')).read_text())
def candidates():return {p.stem:load(p.stem) for p in sorted(MANIFESTS.glob('ffn_wen_*.json'))}
def review_group(name):return 'first'
def copy_tree(source,destination):
    for p in source.rglob('*'):
        if p.is_file():t=destination/p.relative_to(source);t.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(str(p),str(t))
def same_rtl(name,manifest):raise ValueError('Each new hardware candidate requires its own CPU/SAIF/mapping/proof/power')
def feasible(row):return row.get('formal_passed') is True and row['throughput_per_second']>=THROUGHPUT_MIN and row['mean_energy_j']<ENERGY_LIMIT_J and row['metrics']['area']['accelerator_budget_including_shared_interface_mm2']<=AREA_LIMIT
