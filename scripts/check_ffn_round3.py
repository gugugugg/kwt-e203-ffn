"""Use the existing actual-input checker for the round-three candidates."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
from ffn_round3_config import CANDIDATES, ROOT, freeze

parser = argparse.ArgumentParser()
parser.add_argument('variants', nargs='*', choices=list(CANDIDATES))
args = parser.parse_args()
freeze()
out = ROOT / 'reports/optimization/ffn_round3'
out.mkdir(parents=True, exist_ok=True)
for variant in args.variants or CANDIDATES:
    command = [sys.executable, 'scripts/check_optimization_rtl.py', variant, '--linear-only',
               '--package', 'models/kwt_unified_optimized_v1', '--vectors', 'build/optimization/vectors/Q2_range', '--label', 'round3']
    # Existing Q2 vectors are shared with the accepted second-round run.
    old = ROOT / 'reports/optimization/rtl/ffn_v2_MWQPF/Q2_range.json'
    if not old.exists():
        old = next((ROOT / 'reports/optimization/rtl/ffn_v2_MWQPF').glob('*.json'))
    previous = json.loads(old.read_text())
    command[command.index('--vectors')+1] = previous['vectors']
    command[command.index('--package')+1] = previous['package']
    record = {'variant': variant, 'features': CANDIDATES[variant], 'stage': 'rtl_running'}
    path = out / (variant + '.json')
    path.write_text(json.dumps(record, indent=2))
    result = subprocess.run(command, cwd=ROOT, stdout=(out / (variant+'-rtl.log')).open('w'), stderr=subprocess.STDOUT)
    record.update(stage='rtl_passed' if result.returncode==0 else 'rtl_failed', rtl_passed=result.returncode==0)
    path.write_text(json.dumps(record, indent=2))
    print(variant, record['stage'], flush=True)
    if result.returncode:
        sys.exit(result.returncode)
