"""Four-state bus protocol and coarse interface structure checks."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = ROOT / 'reports/encoder_cpu'
    rtl = [ROOT / 'rtl/kwt_sram16x1024_model.sv', ROOT / 'rtl/kwt_spmem16.sv']
    rtl += sorted((ROOT / 'rtl/encoder').glob('*.sv')) + sorted((ROOT / 'rtl/encoder_bus').glob('*.sv'))
    sources = rtl + list((ROOT / 'rtl/encoder').glob('*.svh')) + [ROOT / 'tb/encoder_bus/kwt_icb_encoder_tb.sv', Path(__file__)]
    result = {'status': 'in_progress', 'source_sha256': {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    target = report / 'bus-checks.json'

    def run(name, command):
        with (report / (name + '.log')).open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)

    try:
        run('bus-compile', ['iverilog', '-g2012', '-Irtl/encoder', '-s', 'kwt_icb_encoder_tb', '-o', 'build/encoder_cpu/bus.vvp'] +
            [str(p) for p in rtl] + ['tb/encoder_bus/kwt_icb_encoder_tb.sv'])
        run('bus-run', ['vvp', 'build/encoder_cpu/bus.vvp'])
        text = (report / 'bus-run.log').read_text()
        match = re.search(r'ICB_ENCODER_PROTOCOL_PASS cases=(\d+) response_hold=4', text)
        if not match or int(match[1]) != 25:
            raise RuntimeError('Missing complete bus protocol evidence: ' + text)
        script = 'read_verilog -sv -Irtl/encoder ' + ' '.join(p.relative_to(ROOT).as_posix() for p in rtl)
        script += '; hierarchy -check -top kwt_icb_encoder; proc; opt; memory_dff; memory_collect; opt_clean; check -assert; stat; write_json build/encoder_cpu/interface-structure.json'
        run('interface-structure', ['yosys', '-p', script])
        result.update(status='passed', four_state=True, protocol_cases=25,
                      response_backpressure_cycles=4, structural_problems=0,
                      full_encoder_four_state_simulated=False, target_150mhz_timing_verified=False)
    except Exception:
        result['status'] = 'failed'
        raise
    finally:
        target.write_text(json.dumps(result, indent=2))
    print('ICB encoder protocol and structure passed')


if __name__ == '__main__':
    main()
