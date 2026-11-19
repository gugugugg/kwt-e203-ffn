import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.ffn_channel import ChannelFFN

BUILD = ROOT / 'build/ffn_ablation'
REPORT = ROOT / 'reports/ffn_ablation'


def write_hex(path, values, bits):
    path.write_text(''.join(('%0*x\n' % (bits // 4, int(v) & ((1 << bits) - 1))) for v in np.asarray(values).flat))


def read_hex(path, dtype):
    return np.array([int(v, 16) for v in path.read_text().split()], dtype=dtype)


def run(name, command):
    print(name, flush=True)
    start = time.perf_counter()
    with (REPORT / (name + '.log')).open('w') as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError((REPORT / (name + '.log')).read_text(errors='replace')[-5000:])
    return {'name': name, 'host_seconds': time.perf_counter() - start, 'returncode': result.returncode}


def prepare():
    vectors = BUILD / 'channel_vectors'
    images = BUILD / 'channel_images'
    for folder in [vectors, images]:
        folder.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'build/rtl/vectors/manifest.json').read_text())
    model = ChannelFFN(ROOT / 'models/kwt1_ffn_channel_v1', backend='int64')
    floating = np.load(sorted((ROOT / 'data/numerical/fixed16_v1/ffn_vectors').glob('*.npz'))[0])
    task_nrmse = []
    for task in manifest['ffn_tasks']:
        index, layer = task['index'], task['layer']
        x = read_hex(ROOT / ('build/rtl/vectors/task_%02d_input.hex' % index), '<u2').view('<i2').reshape(99, 64)
        p = model.parameters[layer]
        expected = model.ffn(x, layer, encoded=True)
        write_hex(vectors / ('task_%02d_expected.hex' % index), expected, 16)
        image = read_hex(ROOT / ('build/cpu/images/task_%02d_shared.hex' % index), '<u4')
        half = image.view('<u2')
        half[0x4000 // 2:0x4000 // 2 + 16384] = p['kernel'].view('<u2').ravel()
        half[0xc000 // 2:0xc000 // 2 + 1024] = p['bias'].view('<u2').ravel()
        half[0xc800 // 2:0xc800 // 2 + 128] = p['shift_words']
        write_hex(images / ('task_%02d_shared.hex' % index), image, 32)
        if index < 12:
            reference = floating['layer_%02d_reference_float32' % layer].astype(np.float64)
            delta = model.decode_ffn(expected, layer) - reference
            task_nrmse.append(float(np.sqrt(np.mean(delta * delta)) / max(np.sqrt(np.mean(reference * reference)), 1e-8)))
    shutil.copyfile(ROOT / 'build/cpu/images/task_shifts.hex', images / 'task_shifts.hex')
    source = (ROOT / 'tb/ffn_channel/kwt_cpu_soc.sv').read_text()
    (BUILD / 'kwt_cpu_soc.sv').write_text(source)
    return task_nrmse


def build_sim(mode):
    obj = BUILD / (mode + '_obj')
    native = BUILD / (mode + '_native')
    obj.mkdir(exist_ok=True)
    native.mkdir(exist_ok=True)
    up = ROOT / 'third_party/e203_hbirdv2/rtl/e203'
    files = sorted(up.rglob('*.v'))
    files += [BUILD / 'channel_coarse.v'] if mode == 'coarse' else sorted((ROOT / 'rtl').glob('*.sv'))
    if mode == 'channel':
        files += sorted((ROOT / 'rtl/ffn_channel').glob('*.sv'))
    cmd = ['verilator_bin', '--cc', '--no-timing', '--Wno-fatal', '--top-module', 'kwt_cpu_soc',
           '--Mdir', str(obj), '-Ibuild/cpu', '-I' + str(up / 'core'), '-I' + str(up / 'perips'),
           '-I' + str(up / 'perips/apb_i2c'), '-DDISABLE_SV_ASSERTION=1']
    if mode != 'baseline':
        cmd += ['-DKWT_CHANNEL_VARIANT=1']
    run(mode + '-verilator', cmd + [str(BUILD / 'kwt_cpu_soc.sv')] + [str(p) for p in files])
    include = ROOT / 'tools/oss-cad-suite/share/verilator/include'
    units = sorted(obj.glob('Vkwt_cpu_soc*.cpp')) + [ROOT / 'tb/cpu/sim_main.cpp', include / 'verilated.cpp', include / 'verilated_threads.cpp']
    compiler = shutil.which('g++')

    def compile_unit(path):
        output = native / (path.stem + '.o')
        run(mode + '-native-' + path.stem, [compiler, '-std=c++20', '-O3', '-pthread', '-DVL_TIME_CONTEXT',
            '-DVM_COVERAGE=0', '-DVM_TRACE=0', '-DVM_TIMING=0', '-I' + str(include), '-I' + str(include / 'vltstd'),
            '-I' + str(obj), '-c', str(path), '-o', str(output)])
        return str(output)

    with ThreadPoolExecutor(max_workers=4) as workers:
        objects = list(workers.map(compile_unit, units))
    exe = BUILD / (mode + '_sim.exe')
    run(mode + '-link', [compiler, '-static', '-pthread'] + objects + ['-o', str(exe)])
    return exe


def firmware(name, fast, channel=True):
    folder = BUILD / name
    flags = ['-march=rv32imac_zicsr_zifencei', '-mabi=ilp32', '-msmall-data-limit=0', '-mno-relax',
             '-ffreestanding', '-fno-builtin', '-O2', '-Wall', '-Wextra', '-Werror', '-nostdlib',
             '-Isoftware/kwt', '-Isoftware/kwt_channel', '-Tsoftware/cpu_integration/link.ld', '-Wl,--no-relax']
    if channel:
        flags += ['-DKWT_FAST_IO=' + str(int(fast))]
        sources = ['software/kwt_channel/main_timed.c', 'software/kwt_channel/kwt_channel_driver.c']
    else:
        if fast:
            flags += ['-DKWT_BLOCKING_OUTPUT=1']
        sources = ['software/kwt_perf/main_timed.c', 'software/kwt_perf/kwt_driver_packed.c' if fast else 'software/kwt/kwt_driver.c']
    run(name + '-firmware', ['riscv-none-elf-gcc'] + flags + ['software/cpu_integration/startup.S'] +
        sources + ['-lgcc', '-o', str(folder / 'firmware.elf')])
    run(name + '-objcopy', ['riscv-none-elf-objcopy', '-O', 'binary', str(folder / 'firmware.elf'), str(folder / 'firmware.bin')])
    binary = (folder / 'firmware.bin').read_bytes()
    write_hex(folder / 'firmware_itcm.hex', np.frombuffer(binary + bytes(65536 - len(binary)), dtype='<u8'), 64)


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    names = ['A_baseline', 'B_channel', 'C_fast', 'D_combined']
    for name in names:
        (BUILD / name / 'results').mkdir(parents=True, exist_ok=True)
    task_nrmse = prepare()
    executables = {mode: build_sim(mode) for mode in ['baseline', 'channel']}
    firmware('A_baseline', False, channel=False)
    firmware('C_fast', True, channel=False)
    firmware('B_channel', False)
    firmware('D_combined', True)

    def execute(name):
        channel = name in ['B_channel', 'D_combined']
        fast = name in ['C_fast', 'D_combined']
        reads = (11872 if fast else 23232) + (64 if fast else 128) * int(channel)
        folder = BUILD / name
        cmd = [str(executables['channel' if channel else 'baseline']), '+TASKS=14', '+FIRMWARE=' + str(folder / 'firmware_itcm.hex'),
               '+RESULT_DIR=' + str(folder / 'results'), '+EXPECTED_READS=' + str(reads), '+EXPECTED_WORDS=' + str(23872 if channel else 23744)]
        if channel:
            cmd += ['+IMAGE_DIR=' + str(BUILD / 'channel_images'), '+VECTOR_DIR=' + str(BUILD / 'channel_vectors')]
        step = run(name + '-run', cmd)
        text = (REPORT / (name + '-run.log')).read_text()
        records = [{k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)} for line in text.splitlines() if line.startswith('CPU_TASK_PASS')]
        if len(records) != 14 or 'CPU_ALL_PASS tasks=14 ' not in text:
            raise RuntimeError('Incomplete real-CPU execution ' + name)
        for task in range(14):
            expected = (BUILD / 'channel_vectors' if channel else ROOT / 'build/rtl/vectors') / ('task_%02d_expected.hex' % task)
            actual = folder / 'results' / ('task_%02d_codes.hex' % task)
            if actual.read_text().split() != expected.read_text().split():
                raise RuntimeError('Writeback mismatch ' + name)
        return name, {'tasks': records, 'total_cycles': sum(r['end_to_end_cycles'] for r in records[:12]),
                      'bit_exact_output_words': 14 * 25344, 'firmware_bytes': (folder / 'firmware.bin').stat().st_size,
                      'host_seconds': step['host_seconds']}

    with ThreadPoolExecutor(max_workers=2) as workers:
        variants = dict(workers.map(execute, names))
    prior = json.loads((ROOT / 'reports/ffn_timed_perf/checks.json').read_text())['variants']
    for current, previous in [('A_baseline', 'baseline'), ('C_fast', 'packed32_blocking')]:
        if variants[current]['total_cycles'] != prior[previous]['total_cycles']:
            raise RuntimeError('Original full-window cycle count did not reproduce: ' + current)
    base = variants['A_baseline']['total_cycles']
    for row in variants.values():
        row['cycle_reduction_percent'] = 100 * (1 - row['total_cycles'] / base)
    result = {'status': 'passed', 'variants': variants, 'comparison_tasks': 12, 'tasks_per_variant': 14,
              'channel_real_task_nrmse': task_nrmse, 'timing': 'cold task load request through final shared SRAM output write',
              'shared_sram_bytes': 524288, 'channel_metadata_sram': {'width': 16, 'depth': 128, 'bytes': 256},
              'hardware_scope': 'public E203, original deterministic bus waits, no CPU arithmetic offload'}
    (REPORT / 'cpu.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({name: {k: variants[name][k] for k in ['total_cycles', 'cycle_reduction_percent']} for name in names}, indent=2))


if __name__ == '__main__':
    main()
