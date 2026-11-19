"""Functional checks after coarse synthesis; no technology, area or timing signoff."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report_dir = ROOT / 'reports/encoder'
    target = report_dir / 'netlist-checks.json'
    report = {'status': 'in_progress', 'technology_mapped': False,
              'target_150mhz_timing_verified': False, 'area_power_verified': False,
              'checker_sha256': digest(Path(__file__))}
    target.write_text(json.dumps(report, indent=2))

    def run(name, command):
        print(name, flush=True)
        with (report_dir / (name + '.log')).open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)

    started = time.perf_counter()
    try:
        seal = json.loads((ROOT / 'build/encoder/build-sources.json').read_text())
        for name, expected in seal.items():
            if digest(ROOT / name) != expected:
                raise RuntimeError('Rebuild full encoder first: ' + name)
        for module in ['kwt_encoder_div64', 'kwt_encoder_sqrt128']:
            run('synth-'+module, ['yosys', '-p', f'read_verilog -sv rtl/encoder/{module}.sv; synth -top {module}; check -assert; write_verilog -noattr build/encoder/{module}_netlist.v'])
        run('gate-math-compile', ['iverilog', '-g2012', '-s', 'encoder_math_tb', '-o', 'build/encoder/gate_math.vvp',
                                'build/encoder/kwt_encoder_div64_netlist.v', 'build/encoder/kwt_encoder_sqrt128_netlist.v',
                                'tb/encoder/encoder_math_tb.sv'])
        run('gate-math', ['vvp', 'build/encoder/gate_math.vvp'])
        math_log = (report_dir / 'gate-math.log').read_text()
        if re.findall(r'(DIV_PASS count=151|SQRT_PASS count=129)', math_log) != ['DIV_PASS count=151', 'SQRT_PASS count=129']:
            raise RuntimeError('Missing complete gate-level arithmetic comparison evidence.')
        obj = ROOT / 'build/encoder/coarse-obj'
        native = ROOT / 'build/encoder/coarse-native'
        results = ROOT / 'build/encoder/coarse-results'
        for p in [obj, native, results]:
            p.mkdir(parents=True, exist_ok=True)
        run('coarse-verilator', ['verilator_bin', '--cc', '--Wno-fatal', '--top-module', 'kwt_encoder',
                                '--Mdir', str(obj), 'build/encoder/encoder_coarse.v'])
        cpp = shutil.which('g++')
        include = ROOT / 'tools/oss-cad-suite/share/verilator/include'
        units = sorted(obj.glob('Vkwt_encoder*.cpp')) + [ROOT / 'tb/encoder/sim_encoder.cpp', include / 'verilated.cpp', include / 'verilated_threads.cpp']

        def compile_one(source):
            output = native / (source.stem + '.o')
            command = [cpp, '-std=c++20', '-O2', '-pthread', '-DVL_TIME_CONTEXT', '-DVM_COVERAGE=0', '-DVM_TRACE=0', '-DVM_TIMING=0',
                       '-I'+str(include), '-I'+str(include / 'vltstd'), '-I'+str(obj), '-c', str(source), '-o', str(output)]
            with (report_dir / ('coarse-native-'+source.stem+'.log')).open('w') as stream:
                subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            return str(output)

        print('coarse-native-compile', flush=True)
        with ThreadPoolExecutor(max_workers=4) as workers:
            objects = list(workers.map(compile_one, units))
        run('coarse-link', [cpp, '-static', '-pthread'] + objects + ['-o', str(ROOT / 'build/encoder/encoder_coarse_sim.exe')])
        run('coarse-run', [str(ROOT / 'build/encoder/encoder_coarse_sim.exe'), '1', str(results)])
        text = (report_dir / 'coarse-run.log').read_text()
        if 'ENCODER_ALL_PASS tasks=1 words=6336' not in text:
            raise RuntimeError('Missing synthesized full twelve-layer completion.')
        for kind in ['output', 'trace']:
            actual = results / f'task_00_{kind}.bin'
            expected = ROOT / 'build/encoder/vectors' / ('task_00_expected.bin' if kind == 'output' else 'task_00_trace.bin')
            if digest(actual) != digest(expected):
                raise RuntimeError('Coarse synthesized result differs: ' + kind)
        design = json.loads((ROOT / 'build/encoder/structure.json').read_text())
        memories = {}

        def walk(name):
            for cell in design['modules'][name].get('cells', {}).values():
                if cell['type'] == '$mem_v2':
                    p = cell['parameters']
                    if int(p['WIDTH'], 2) != 16 or int(p['SIZE'], 2) not in [128, 1024, 4096]:
                        raise RuntimeError('Unexpected SRAM shape.')
                    if int(p['RD_CLK_ENABLE'], 2) != 1 or int(p['WR_PORTS'], 2) != 1:
                        raise RuntimeError('SRAM has an asynchronous read or multiple writes.')
                    key = '16x' + str(int(p['SIZE'], 2))
                    memories[key] = memories.get(key, 0) + 1
                elif cell['type'] in design['modules']:
                    walk(cell['type'])

        walk('kwt_encoder')
        if memories != {'16x1024': 136, '16x128': 10}:
            raise RuntimeError('Unexpected SRAM allocation: ' + str(memories))
        report.update(status='passed', source_sha256=seal, coarse_netlist_sha256=digest(ROOT / 'build/encoder/encoder_coarse.v'),
                      primitive_generic_gate_cases={'division': 151, 'sqrt': 129},
                      complete_encoder_coarse_tasks=1, final_output_words=6336,
                      intermediate_words=1603800, memory_instances=memories, internal_sram_bytes=281088,
                      all_read_ports_synchronous=True, all_write_ports_single=True,
                      elapsed_host_seconds=time.perf_counter()-started)
    except Exception:
        report['status'] = 'failed'
        raise
    finally:
        target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['status', 'internal_sram_bytes', 'complete_encoder_coarse_tasks']}))


if __name__ == '__main__':
    main()
