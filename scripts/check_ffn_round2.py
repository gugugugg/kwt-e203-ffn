"""Execute actual-input ablations and the normal delayed/single-word consumer scenarios."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/optimization/ffn_round2'
OUT.mkdir(parents=True, exist_ok=True)
def check(variant):
    cmd = ['python', 'scripts/check_optimization_rtl.py', variant, '--linear-only',
           '--package', 'models/kwt_unified_optimized_v1', '--vectors',
           'build/optimization/quantization/Q2_training_range', '--label', 'actual12']
    with (OUT / (variant + '-check.log')).open('w') as log:
        subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if variant in ['ffn_v2_F', 'ffn_v2_MWQPF']:
            for label, option in [('delayed_consumer', '--stall-output'), ('single_consumer', '--single-output')]:
                subprocess.run(cmd[:-1] + [label, '--skip-build', option], cwd=ROOT,
                               stdout=log, stderr=subprocess.STDOUT, check=True)
    print('ACTUAL_INPUT_PASS', variant, flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:
    list(pool.map(check, ['ffn_v2_M', 'ffn_v2_W', 'ffn_v2_Q', 'ffn_v2_P',
                          'ffn_v2_F', 'ffn_v2_R2', 'ffn_v2_MWQP', 'ffn_v2_MWQPF']))
rows = [json.loads((ROOT / 'reports/optimization/rtl' / name / 'actual12.json').read_text())
        for name in ['ffn_v2_M','ffn_v2_W','ffn_v2_Q','ffn_v2_P','ffn_v2_F','ffn_v2_R2','ffn_v2_MWQP','ffn_v2_MWQPF']]
(OUT / 'rtl-ablation.json').write_text(json.dumps(rows, indent=2))
