"""Independent four-state real-CPU task, retaining public RTL #1 delays."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report = ROOT / 'reports/cpu'
    output = ROOT / 'build/cpu/event_results'
    output.mkdir(parents=True, exist_ok=True)
    seal = json.loads((ROOT / 'build/cpu/build-sources.json').read_text())
    for name, expected in seal.items():
        if digest(ROOT / name) != expected:
            raise RuntimeError('Rebuild the CPU integration first: ' + name)
    up = ROOT / 'third_party/e203_hbirdv2/rtl/e203'
    # Icarus inherits `timescale in compilation order. Put this wrapper FIRST,
    # so every unmodified upstream artificial #1 delay means 1 ns, not 1 s.
    files = ['tb/cpu/kwt_cpu_event_tb.sv', 'tb/cpu/kwt_cpu_soc.sv']
    files += [str(p) for p in sorted(up.rglob('*.v'))]
    files += [str(p) for p in sorted((ROOT / 'rtl').glob('*.sv'))]
    command = ['iverilog', '-g2012', '-DDISABLE_SV_ASSERTION=1', '-Ibuild/cpu',
               '-I' + str(up / 'core'), '-I' + str(up / 'perips'),
               '-I' + str(up / 'perips/apb_i2c'), '-s', 'kwt_cpu_event_tb',
               '-o', 'build/cpu/event.vvp'] + files
    start = time.perf_counter()
    result = {'status': 'in_progress', 'task_count': 1, 'simulation': 'Icarus four-state, 1ns/1ps, original #1 delays',
              'source_sha256': seal, 'checker_sha256': digest(Path(__file__)),
              'firmware_elf_sha256': digest(ROOT / 'build/cpu/firmware.elf')}
    target = report / 'event-check.json'

    def save():
        target.write_text(json.dumps(result, indent=2), encoding='utf-8')

    save()
    try:
        for name, args in [('event-compile', command), ('event-run', [
                'vvp', '-v', 'build/cpu/event.vvp', '+TASKS=1', '+RESULT_DIR=build/cpu/event_results'])]:
            print(name, flush=True)
            with (report / (name + '.log')).open('w', encoding='utf-8') as stream:
                subprocess.run(args, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=900)
        text = (report / 'event-run.log').read_text()
        if 'CPU_ALL_PASS tasks=1 output_words=25344 ' not in text or 'PASS four-state real E203 CPU integration' not in text:
            raise RuntimeError('Missing four-state CPU completion evidence.')
        actual = output / 'task_00_codes.hex'
        expected = ROOT / 'build/rtl/vectors/task_00_expected.hex'
        if actual.read_text().split() != expected.read_text().split():
            raise RuntimeError('Four-state CPU writeback differs from the frozen integer reference.')
        result.update(status='passed', output_words_bit_exact=25344, result_sha256=digest(actual),
                      elapsed_host_seconds=time.perf_counter() - start,
                      official_platform_integrated=False, target_150mhz_timing_verified=False)
    except Exception:
        result['status'] = 'failed'
        raise
    finally:
        save()
    print(json.dumps({key: result[key] for key in ['status', 'task_count', 'output_words_bit_exact']}), flush=True)


if __name__ == '__main__':
    main()
