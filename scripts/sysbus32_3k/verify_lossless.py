"""Verify the CH final netlist and measure its complete mapped cold windows."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import importlib.util
import os
import re
import sys

from native_soc import ROOT, REPORT, SOC, flow


def replace(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def prove(final):
    work = REPORT / 'proof'
    work.mkdir(exist_ok=True)
    hold = flow.read(flow.PROFILES / (flow.NAME + '_hold.json'))
    profile = flow.read(ROOT / final['profile'])
    stages = [('rtl_to_hold', 'complete', hold), ('raw_to_hold', 'electrical', hold),
              ('hold_to_final', 'electrical', profile)]
    for name, kind, checkpoint in stages:
        tcl = work / (name + '.tcl')
        log = work / (name + '.log')
        receipt = work / (name + '.json')
        if receipt.is_file():
            assert flow.read(receipt)['checkpoint'] == checkpoint
            continue
        text = (ROOT / ('scripts/server/verify_optimization_' + kind + '.tcl')).read_text()
        text = replace(text, 'exec find build/server/technology', 'exec find -L build/server/technology')
        text = re.sub(r'(?m)^set report .*$', 'set report $env(XPIAN_PROOF_REPORT)', text)
        tcl.write_text(text)
        env = dict(os.environ, XPIAN_OPT_VARIANT=flow.NAME, XPIAN_TAG=checkpoint['tag'],
                   XPIAN_OPT_SVF_CHAIN=' '.join(checkpoint['svf_chain']),
                   XPIAN_DRC_FROM=checkpoint['synthesis_from'], XPIAN_PROOF_REPORT=str(work / name))
        flow.flow.run('fm_shell', tcl, log, env)
        assert 'Verification SUCCEEDED' in log.read_text(errors='replace'), log
        flow.write(receipt, dict(passed=True, checkpoint=checkpoint))
        print('LOSSLESS_PROOF_PASS', name, flush=True)


def mapped_bench(netlist):
    # Reuse physical macro and firmware-preload lookup from the existing mapped flow.
    spec = importlib.util.spec_from_file_location('mapped_macros', ROOT / 'scripts/trb_threebank/mapped.py')
    module = importlib.util.module_from_spec(spec)
    original = sys.modules['native']
    sys.modules['native'] = type('MappedImports', (), dict(ROOT=ROOT, NAME=flow.NAME, REPORT=REPORT,
        OUT=SOC, DEST=flow.DEST, read=flow.read, save=flow.write, job=flow.job))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules['native'] = original
    mapped_text = netlist.read_text()
    tcm, shared = module.paths(mapped_text)
    bench = (SOC / 'complete_soc_tb.sv').read_text()
    bench = re.sub(r'(?m)^    wire \[31:0\] inspect_pc=.*;\n', '', bench)
    bench = bench.replace(' pc=%h', '').replace(',inspect_pc', '')
    bench = re.sub(r'(?m)^    wire \[3:0\] cpu_mask=.*;\n', '', bench)
    masters, = re.findall(r'(?ms)^\s*kwt_sysbus_masters\s+shared_masters\s*\((.*?)\);', mapped_text)
    cpu_path = 'dut.soc.u_e203_subsys_main.'

    def signal(ports, port, parent):
        inverted, value = re.search(r'\.' + port + r'(_BAR)?\(\s*(\w+|1\x27b[01])\s*\)', ports).groups()
        return ('!' if inverted else '') + (value if "'" in value else parent + value)

    for name, port in [('cpu_address', 'addr'), ('cpu_data', 'wdata'), ('cpu_read', 'read')]:
        expression = signal(masters, 'cpu_cmd_' + port, cpu_path)
        bench = re.sub(r'(?m)(^    wire (?:\[31:0\] )?' + name + r'=).*;', r'\g<1>' + expression + ';', bench)
    fire = '&&'.join(signal(masters, 'cpu_cmd_' + port, cpu_path) for port in ('valid', 'ready'))
    bench = re.sub(r'(?m)^    wire cpu_fire=.*;', '    wire cpu_fire=' + fire + ';', bench)
    physical = module.physical_probe(shared)
    physical += "\n    wire [3:0] physical_result_mask=4'hf;"
    bench = re.sub(r'(?m)^    wire result_fire=.*\n.*;\n', lambda _: physical + '\n', bench)
    input_reads = []
    for bank in (0, 8, 9, 10):
        lo, hi = shared[bank][0], shared[bank][1]
        input_reads.append('(!%s.CEN&&%s.GWEN&&!%s.CEN&&%s.GWEN)' % (lo, lo, hi, hi))
    bench = re.sub(r'(?m)^    wire source_fire=.*;\n',
                   '    wire source_fire=' + '||'.join(input_reads) + ';\n', bench)
    ack_ports, = re.findall(r'(?ms)^\s*kwt_sysbus_issue\s+\w+\s*\((.*?)\);', mapped_text)
    ack = [signal(ack_ports, port, cpu_path + 'u_e203_subsys_perips.accelerator.')
           for port in ('result_ack', 'result_ack_ready')]
    bench = re.sub(r'(?m)^    wire result_ack=.*\n.*;\n', '    wire result_ack=' + '&&'.join(ack) + ';\n', bench)
    for original, mapped in [('addr', 'addr'), ('wdata', 'data'), ('wmask', 'mask')]:
        bench = bench.replace('dut.shared_memory.memory.' + original, 'physical_result_' + mapped)
    begin = bench.index('        force dut.soc.')
    end = bench.index('        for(integer b=0;b<64;', begin)
    # Leave the original System Bus mailbox initialization in the testbench.
    boot = module.preload(tcm, shared[31]).split('        for(integer b=0;b<64;', 1)[0]
    bench = bench[:begin] + boot + ('        boot_phase=0;\n        @(negedge reference_clk);rst_n=1;\n'
                                   '        wait(system_reset_n===1\'b1);\n') + bench[end:]
    bench = re.sub(r'(?ms)^`ifdef KWT_UNIFIED_GATE\n    string sdf_path;.*?^`endif\n', '', bench)
    bench = re.sub(r'(?ms)^`ifndef KWT_UNIFIED_GATE\n`ifndef VERILATOR\n(.*?)^`endif\n`endif\n',
                   lambda match: match[1], bench)
    return bench.replace('$set_gate_level_monitoring("rtl_on")', '$set_gate_level_monitoring("on")')


def capture(final, cpu):
    work = REPORT / 'gate-activity'
    work.mkdir(exist_ok=True)
    netlist = ROOT / ('build/server/complete_soc_sm40_' + final['tag']) / 'netlist.v'
    binary = work / 'sim'
    if not binary.is_file():
        bench = work / 'gate_tb.sv'
        bench.write_text(mapped_bench(netlist))
        models = [line for line in (SOC / 'files.f').read_text().splitlines()
                  if '/mem_gen/' in line or line.startswith('/storage1/') or
                  line.endswith(('/ROM1KX32.v', '/scc40nll_vhsc40_rvt.v'))]
        sources = work / 'gate_files.f'
        sources.write_text('\n'.join(models + [str(netlist), str(bench)]) + '\n')
        flow.job(['vcs', '-full64', '-sverilog', '+delay_mode_distributed', '+notimingcheck',
                  '-timescale=1ns/1ps', '+define+ARM_UD_MODEL+KWT_UNIFIED_GATE+DISABLE_SV_ASSERTION=1',
                  '-debug_access+all', '+incdir+'+str(SOC), '-top', 'complete_soc_tb', '-f', sources,
                  '-Mdir='+str(work / 'csrc'), '-o', binary], work / 'compile.log')

    def run(row):
        case = row['case']
        log = work / ('run_%02d.log' % case)
        activity = work / ('activity_%02d.saif' % case)
        if not (log.is_file() and activity.is_file() and 'UNIFIED_PUBLIC_ALL_PASS' in log.read_text()):
            flow.job([binary, '+FIRST_TASK='+str(case), '+TASKS=1', '+RESULT_DIR='+str(work),
                      '+SAIF='+str(work/'activity')], log)
        text = log.read_text()
        assert 'UNIFIED_PUBLIC_ALL_PASS' in text, log
        for marker in ('SYSBUS3K_COUNTS', 'UNIFIED_PUBLIC_TASK_PASS'):
            line, = re.findall(r'(?m)^' + marker + r' (.*)$', text)
            for name, value in re.findall(r'(\w+)=(\d+)', line):
                assert int(value) == row[name], (case, name, value, row[name])
        with activity.open() as stream:
            header = ''.join(next(stream) for _ in range(16))
        scale, unit = re.search(r'\(TIMESCALE\s+(\d+)\s+(ns|ps|fs)\)', header).groups()
        duration = Decimal(re.search(r'\(DURATION\s+([.\d]+)\)', header)[1]) * int(scale)
        duration *= dict(ns=Decimal(1), ps=Decimal('0.001'), fs=Decimal('0.000001'))[unit]
        observed = Decimal(re.search(r'UNIFIED_SAIF_SAVED .* duration_ns=([.\d]+)', text)[1])
        assert abs(duration - observed) < Decimal('0.01'), (case, duration, observed)
        print('LOSSLESS_GATE_PASS', case, row['cycles'], flush=True)
        return dict(case=case, cycles=row['cycles'], duration_ns=str(duration), saif=str(activity))

    rows = [run(cpu['cases'][0])]
    with ThreadPoolExecutor(max_workers=flow.settings()['cpu_case_workers']) as pool:
        rows.extend(pool.map(run, cpu['cases'][1:]))
    flow.write(work/'result.json', dict(tag=final['tag'], passed=True, captures=rows))


def power(final):
    captured = flow.read(REPORT/'gate-activity/result.json')
    assert captured['tag'] == final['tag'] and captured['passed']
    work = REPORT / 'gate-power'
    work.mkdir(exist_ok=True)
    text = (SOC / 'eda/power.tcl').read_text().split('\nupdate_timing\n', 1)[0]
    assert 'power_analysis_mode averaged' in text and 'saif_map' not in text
    text = re.sub(r'(?m)^set report .*$', 'set report $env(XPIAN_POWER_REPORT)', text)
    tcl = work / 'power.tcl'
    tcl.write_text(text + '''
update_timing
if {![read_saif -strip_path complete_soc_tb/dut $env(XPIAN_ACTIVITY)]} {error "Gate SAIF annotation failed"}
update_power
redirect $report/power.rpt {report_power -verbose -hierarchy}
source scripts/server/export_optimization_power.tcl
redirect $report/annotation.rpt {report_switching_activity}
redirect $report/unannotated.rpt {report_switching_activity -list_not_annotated}
puts "LOSSLESS_GATE_POWER_DONE"
exit
''')

    def run(row):
        folder = work / ('case_%02d' % row['case'])
        folder.mkdir(exist_ok=True)
        log = folder/'pt.log'
        values = folder/'power_values.json'
        if not (values.is_file() and log.is_file() and 'LOSSLESS_GATE_POWER_DONE' in log.read_text()):
            env = dict(os.environ, XPIAN_TAG=final['tag'], XPIAN_CORNER='ss',
                       XPIAN_POWER_REPORT=str(folder), XPIAN_ACTIVITY=row['saif'])
            flow.flow.run('pt_shell', tcl, log, env)
        data = flow.read(values)
        assert 'LOSSLESS_GATE_POWER_DONE' in log.read_text() and data['unit'] == 'W' and data['total_w'] > 0
        print('LOSSLESS_POWER_PASS', row['case'], data['total_w'], flush=True)
        return dict(row, **data)

    with ThreadPoolExecutor(max_workers=flow.settings()['power_case_workers_per_candidate']) as pool:
        rows = list(pool.map(run, captured['captures']))
    cycles = sum(row['cycles'] for row in rows)
    weighted = sum(row['total_w'] * row['cycles'] for row in rows)
    flow.write(work/'result.json', dict(tag=final['tag'], clock_hz=150000000, cycles_total=cycles,
               throughput=12*150000000/cycles, mean_power_w=weighted/cycles,
               mean_energy_j=weighted/(12*150000000), measurements=rows,
               activity='same final gate netlist, distributed model delays, no SDF'))


if __name__ == '__main__':
    flow.preflight()
    final = flow.read(REPORT/'final-screen.json')
    assert final['timing_passed']
    stage = sys.argv[1]
    if stage == 'proof':
        prove(final)
    elif stage == 'capture':
        capture(final, flow.read(REPORT/'cpu-result.json'))
    elif stage == 'power':
        power(final)
