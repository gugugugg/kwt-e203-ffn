import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'reports/optimization/ffn_trb_128mac'
REPORT = ROOT / 'reports/optimization/ffn_trb_pair_mac'
WORK = ROOT / 'build/optimization/ffn_trb_pair_mac'


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
