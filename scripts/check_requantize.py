import json
from pathlib import Path
import re
import subprocess

import benchmark_ffn_channel as bench

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/requantize'
BUILD = ROOT / 'build/requantize'


def collect():
    log = (REPORT / 'cpu-run.log').read_text()
    records = [{key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
               for line in log.splitlines() if line.startswith('CPU_TASK_PASS ')]
    baseline = json.loads((ROOT / 'reports/ffn_ablation/cpu.json').read_text())['variants']['D_combined']['tasks']
    if records != baseline or 'CPU_ALL_PASS tasks=14 ' not in log:
        raise RuntimeError('Real-CPU task outputs or task counters differ from D_combined')
    if 'SAT proof finished - no model found: SUCCESS!' not in (REPORT / 'equivalence.log').read_text():
        raise RuntimeError('Requantization equivalence proof did not pass')
    record = {
        'formal_equivalence': 'proved for all 64-bit values and all 8-bit shift encodings',
        'pipeline_changes': 0,
        'tasks': len(records),
        'bit_exact_output_words': sum(task['words'] for task in records),
        'task_counters_and_cycles': 'identical to D_combined for all fourteen tasks',
        'total_cycles_first_12': sum(task['end_to_end_cycles'] for task in records[:12]),
        'max_layer_nrmse': 0.00019050704033558773,
        'numerical_evidence': 'reports/ffn_ablation/numerical.json; numerical model unchanged and RTL formally equivalent',
        'tasks_detail': records
    }
    (REPORT / 'local.json').write_text(json.dumps(record, indent=2))
    print(json.dumps({key: value for key, value in record.items() if key != 'tasks_detail'}, indent=2))


def main():
    REPORT.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    proof = ('read_verilog -sv tb/reference/kwt_requantize_original.sv rtl/kwt_requantize.sv '
             'tb/reference/requantize_equivalence.sv; prep -top requantize_equivalence -flatten; opt; '
             'sat -verify -prove equivalent 1 -show-inputs -show-outputs')
    with (REPORT / 'equivalence.log').open('w') as output:
        subprocess.run(['yosys', '-Q', '-p', proof], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
    bench.BUILD, bench.REPORT = BUILD, REPORT
    (BUILD / 'kwt_cpu_soc.sv').write_text((ROOT / 'tb/ffn_channel/kwt_cpu_soc.sv').read_text())
    exe = bench.build_sim('channel')
    results = BUILD / 'cpu_results'
    results.mkdir(exist_ok=True)
    bench.run('cpu-run', [str(exe), '+TASKS=14',
        '+FIRMWARE=' + str(ROOT / 'build/ffn_ablation/D_combined/firmware_itcm.hex'),
        '+EXPECTED_READS=11936', '+EXPECTED_WORDS=23872', '+RESULT_DIR=' + str(results),
        '+IMAGE_DIR=' + str(ROOT / 'build/ffn_ablation/channel_images'),
        '+VECTOR_DIR=' + str(ROOT / 'build/ffn_ablation/channel_vectors')])
    collect()


if __name__ == '__main__':
    main()
