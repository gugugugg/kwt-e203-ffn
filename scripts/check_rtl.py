"""Reproducible local RTL checks; explicit separation from official SoC signoff."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/rtl'
RTL = ['rtl/kwt_requantize.sv', 'rtl/kwt_dot64.sv', 'rtl/kwt_sram16x1024_model.sv',
       'rtl/kwt_spmem16.sv', 'rtl/kwt_ffn.sv', 'rtl/kwt_icb_control.sv', 'rtl/kwt_icb_ffn.sv']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-full-ffn', action='store_true', help='Quick development only; report marks full FFN skipped')
    args = parser.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    (ROOT / 'build/rtl').mkdir(parents=True, exist_ok=True)
    steps = []
    report = {'status': 'in_progress', 'steps': steps}
    path = REPORTS / 'checks.json'

    def save():
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')

    def run(name, arguments):
        print(name, flush=True)
        start = time.perf_counter()
        with (REPORTS / (name + '.log')).open('w', encoding='utf-8') as stream:
            result = subprocess.run(arguments, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        steps.append({'name': name, 'exit_code': result.returncode,
                      'elapsed_host_seconds': time.perf_counter()-start})
        save()
        if result.returncode:
            raise RuntimeError(name + ': ' + (REPORTS / (name + '.log')).read_text(encoding='utf-8', errors='replace')[-4500:])

    save()
    try:
        run('generate-vectors', [sys.executable, 'scripts/generate_rtl_vectors.py'])
        for name, top, sources in [
            ('requant', 'kwt_requantize_tb', RTL[:1]),
            ('dot64', 'kwt_dot64_tb', RTL[:2]),
            ('ffn', 'kwt_ffn_tb', RTL[:5]),
            ('icb', 'kwt_icb_ffn_tb', RTL),
        ]:
            if name == 'ffn' and args.skip_full_ffn:
                continue
            run(name+'-compile', ['iverilog','-g2012','-I','build/rtl/vectors','-s',top,
                                 '-o',f'build/rtl/{name}.vvp'] + sources + [f'tb/rtl/{top}.sv'])
            run(name+'-simulation', ['vvp',f'build/rtl/{name}.vvp'])
        run('verilator-lint', [str(ROOT / 'tools/oss-cad-suite/bin/verilator_bin.exe'),
                              '--lint-only','-Wall','--top-module','kwt_icb_ffn'] + RTL)
        synth = 'read_verilog -sv ' + ' '.join(RTL[:2]) + '; synth -top kwt_dot64; check -assert; write_verilog -noattr build/rtl/dot64-netlist.v; stat'
        run('dot64-synthesis', ['yosys','-p',synth])
        run('dot64-gates-compile', ['iverilog','-g2012','-I','build/rtl/vectors','-s','kwt_dot64_tb',
                                  '-o','build/rtl/dot64-gates.vvp','build/rtl/dot64-netlist.v','tb/rtl/kwt_dot64_tb.sv'])
        run('dot64-gates', ['vvp','build/rtl/dot64-gates.vvp'])
        structure = 'read_verilog -sv ' + ' '.join(RTL) + '; hierarchy -check -top kwt_icb_ffn; proc; opt; memory_dff; memory_collect; opt_clean; check -assert; stat; write_json build/rtl/ffn-structure.json'
        run('ffn-structure', ['yosys','-p',structure])
        run('riscv-driver-compile', ['riscv-none-elf-gcc','-march=rv32imac','-mabi=ilp32',
                                    '-ffreestanding','-O2','-Wall','-Wextra','-Werror','-c',
                                    'software/kwt/kwt_driver.c','-o','build/rtl/kwt_driver.o'])
        upstream = ROOT / 'third_party/e203_hbirdv2'
        commit = subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'], text=True).strip()
        official = json.loads((REPORTS / 'e203-upstream-commit.json').read_text())['sha']
        dirty = subprocess.check_output(['git','-C',str(upstream),'status','--porcelain','--untracked-files=no'], text=True).strip()
        if commit != official or dirty:
            raise RuntimeError('Public E203 checkout differs from verified source.')
        files = sorted((upstream/'rtl/e203').rglob('*.v')) + sorted((upstream/'tb').glob('*.v'))
        run('e203-elaboration', ['iverilog','-g2005-sv','-Diverilog','-DDISABLE_SV_ASSERTION=1',
                                 '-s','tb_top','-o','build/rtl/e203-public-soc.vvp',
                                 '-I',str(upstream/'rtl/e203/core'),'-I',str(upstream/'rtl/e203/perips'),
                                 '-I',str(upstream/'rtl/e203/perips/apb_i2c')] + [str(p) for p in files])
        vectors = json.loads((ROOT/'build/rtl/vectors/manifest.json').read_text())
        sources = [ROOT/p for p in RTL] + list((ROOT/'tb/rtl').glob('*.sv')) + [
            ROOT/'scripts/check_rtl.py', ROOT/'scripts/Check-RTL.ps1', ROOT/'scripts/generate_rtl_vectors.py',
            ROOT/'software/kwt/kwt_driver.c', ROOT/'software/kwt/kwt_driver.h']
        report.update(status='passed', entry_group='undergraduate', date='2026-10-21',
                      scope='local first-FFN RTL and public-E203 interface preparation',
                      numerical_package_sha256=vectors['parameter_manifest_sha256'],
                      dot_cases=vectors['dot_cases'],requant_cases=vectors['requant_cases'],
                      complete_ffn_tasks=None if args.skip_full_ffn else len(vectors['ffn_tasks']),
                      full_ffn_skipped=args.skip_full_ffn,
                      ffn_output_words_bit_exact=None if args.skip_full_ffn else len(vectors['ffn_tasks'])*99*256,
                      icb_task_output_words_bit_exact=99*256,
                      public_e203_commit=commit, public_e203_files_elaborated=len(files),
                      public_e203_cpu_firmware_executed=False, official_platform_integrated=False,
                      sram_models='28 synchronous 16x1024 functional leaves; not foundry macros',
                      technology_timing_area_power_verified=False, full_encoder_rtl_completed=False,
                      official_600_evaluated=False, no_vpn_downloads=True,
                      source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
        save()
        print(json.dumps({key: report[key] for key in ['status','dot_cases','requant_cases',
                                                      'complete_ffn_tasks','ffn_output_words_bit_exact',
                                                      'public_e203_commit']}, indent=2), flush=True)
    except Exception:
        report['status']='failed'
        save()
        raise


if __name__ == '__main__':
    main()
