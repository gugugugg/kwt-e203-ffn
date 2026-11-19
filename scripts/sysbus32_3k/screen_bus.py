"""Run both write-response modes through the unchanged E203 memory bus."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
REPORT = ROOT / 'reports/optimization/ffn_sysbus32_3k'
UPSTREAM = ROOT / 'build/server/official_2025/e203_hbirdv2-master/rtl/e203'
SOC = ROOT / 'build/optimization/complete_soc/ffn_trb_sysbus32'
SRAM = ROOT / ('reports/optimization/ffn_literature_power/recovery/actual-compilation-sources/'
               'external-models/storage1/admin_public_dir/SRAM_Lib_2025/RAMSP4096X16/verilog/RAMSP4096X16.v')


def run(command, log):
    with log.open('w', encoding='utf-8') as stream:
        subprocess.run([str(item) for item in command], cwd=str(ROOT), stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=90)
    return log.read_text(encoding='utf-8')


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    attempt = len(list(REPORT.glob('attempt-*'))) + 1
    folder = REPORT / ('attempt-%02d' % attempt)
    folder.mkdir()
    # Icarus needs a local net on the macro output before the generated slice.
    wrapper = (ROOT / 'rtl/public_encoder/kwt_shared_sram_sm40.sv').read_text(encoding='utf-8')
    wrapper = wrapper.replace('            RAMSP4096X16 macro(', '            wire [15:0] q;\n'
                              '            localparam integer Q_OFFSET = bank*32+half*16;\n'
                              '            assign bank_data[Q_OFFSET+:16] = q;\n'
                              '            RAMSP4096X16 macro(')
    wrapper = wrapper.replace('.Q(bank_data[bank*32+half*16+:16])', '.Q(q)')
    wrapper = wrapper.replace('            wire [15:0] q;', '            wire [15:0] q;\n'
                              '            localparam [4:0] BANK_INDEX = bank;\n'
                              '            localparam integer BYTE_OFFSET = half*2;\n'
                              '            localparam integer DATA_OFFSET = half*16;')
    wrapper = wrapper.replace('==bank', '==BANK_INDEX').replace('half*2+1]', 'BYTE_OFFSET+1]')
    wrapper = wrapper.replace('half*2]', 'BYTE_OFFSET]').replace('wdata[half*16+:16]', 'wdata[DATA_OFFSET+:16]')
    memory = folder / 'kwt_shared_sram_sm40.sv'
    memory.write_text(wrapper, encoding='utf-8')
    # The public DFF model contains #1 without its own timescale.
    sources = [HERE / 'bus_tb.sv'] + [UPSTREAM / item for item in (
        'subsys/e203_subsys_mems.v', 'fab/sirv_icb1to8_bus.v', 'general/sirv_gnrl_bufs.v',
        'general/sirv_gnrl_dffs.v', 'general/sirv_gnrl_icbs.v', 'general/sirv_gnrl_xchecker.v',
        'perips/sirv_expl_axi_slv.v',
    )] + [SOC / 'sirv_mrom_top.v', SOC / 'ROM1KX32.v', memory,
          SRAM, ROOT / 'scripts/trb_sysbus32/shared.sv', ROOT / 'scripts/trb_sysbus32/masters.sv',
          HERE / 'write_ack.sv']
    measurements = {}
    for mode in (0, 1):
        output = folder / ('mode-%d.vvp' % mode)
        run(['iverilog', '-g2012', '-s', 'bus_tb', '-DARM_UD_MODEL', '-DDISABLE_SV_ASSERTION=1',
             '-I', UPSTREAM / 'core', '-Pbus_tb.COMMIT_ACK=%d' % mode, '-o', output] + sources,
            folder / ('mode-%d-compile.log' % mode))
        log = run(['vvp', output], folder / ('mode-%d-run.log' % mode))
        phases = {}
        for line in log.splitlines():
            if line.startswith('BUS_PHASE '):
                name = re.search(r'phase=(\w+)', line)[1]
                phases[name] = dict((key, int(value)) for key, value in re.findall(r'(\w+)=(\d+)', line))
        assert len(phases) == 4 and 'BUS_PASS mode=%d ' % mode in log
        measurements['commit_ack' if mode else 'registered_ack'] = phases
        print(log, end='')
    # Continuous streams can precede the opposite direction only after retiring
    # the old response. Use the sustained rates without charging extra turns.
    candidate = measurements['commit_ack']
    assert candidate['writes']['min_gap'] == candidate['writes']['max_gap']
    assert candidate['reads']['min_gap'] == candidate['reads']['max_gap']
    write_gap, read_gap = candidate['writes']['max_gap'], candidate['reads']['max_gap']
    baseline = json.loads((REPORT.parent / 'ffn_trb_sysbus32/cpu-result.json').read_text(encoding='utf-8'))
    case = baseline['cases'][0]
    writes = sum(case[key] for key in ('host_payload', 'host_setup', 'host_control', 'dma_writes'))
    reads = case['dma_reads']
    # A synchronous read needs a separate retirement cycle. A final write
    # only needs its commit edge, so no response tail is included for it.
    bound = writes * write_gap + reads * read_gap
    result = dict(measurements=measurements, task_writes=writes, task_reads=reads, ideal_service_cycles=bound,
                  ideal_tasks_s=150000000 / bound, cycles_remaining_at_3000=50000 - bound,
                  logs=folder.relative_to(ROOT).as_posix())
    (REPORT / 'bus-screen.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
