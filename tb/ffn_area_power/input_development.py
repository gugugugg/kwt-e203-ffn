"""Run existing normal FFN scenarios with the two-macro input transform."""
from pathlib import Path
from datetime import datetime
import argparse
import json
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'scripts/server')]
from area_power_input import transform_core, transform_wrapper
from check_ffn_post_dma_rtl_native import bench, vectors
from tile_pipeline_observers import adapt_native_bench


def input_bench():
    text = adapt_native_bench(bench(dict(dma=True, output_dma=True)), ['BP', 'E2'])
    text = text.replace('localparam LD_DMA=1,LD_OUTPUT=1;',
                        'wire LD_DMA=!mixed_access&&!single_access;\n    localparam LD_OUTPUT=1;')
    text = text.replace('else if(mixed_access&&(address%17==0||address+1==count))',
                        'else if(single_access||(mixed_access&&(address%17==0||address+1==count)))')
    text = text.replace('else if(mixed_access&&(at%17==0||at+1==last))',
                        'else if(single_access||(mixed_access&&(at%17==0||at+1==last)))')
    summary = '''            if(ap_input_halves!=6336||ap_input_rows_complete!=99||ap_input_reads!=101376||ap_input_slot_changes!=98)
                $fatal(1,"INPUT_TASK_COUNTS half=%0d rows=%0d reads=%0d flips=%0d",ap_input_halves,ap_input_rows_complete,ap_input_reads,ap_input_slot_changes);
            if(ap_input_packed_low!=ap_input_flush_high)
                $fatal(1,"INPUT_PACKED_FLUSH_COUNT");
            $display("FFN_INPUT_RTL_PASS layer=%0d halves=%0d rows=%0d reads=%0d flips=%0d single=%0d packed_low=%0d flush_high=%0d",layer,ap_input_halves,ap_input_rows_complete,ap_input_reads,ap_input_slot_changes,ap_input_single,ap_input_packed_low,ap_input_flush_high);
'''
    text = text.replace('            active=0;$display("FFN_NEXT_RTL_PASS',
                        summary + '            active=0;$display("FFN_NEXT_RTL_PASS')
    at = text.index('    initial begin')
    return text[:at] + (ROOT / 'tb/ffn_area_power/input_observer.svh').read_text() + text[at:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenarios', nargs='+', choices=['actual12', 'mixed_paused', 'single'],
                        default=['actual12', 'mixed_paused', 'single'])
    args = parser.parse_args()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out = ROOT / 'build/optimization/ffn_area_power/development/input' / stamp
    report = ROOT / 'reports/optimization/ffn_area_power/development/input' / stamp
    out.mkdir(parents=True)
    report.mkdir(parents=True)
    source = out / 'rtl_sources'
    shutil.copytree(ROOT / 'build/optimization/rtl_sources/ffn_tp_CROSS', source)
    core = source / 'encoder/kwt_encoder.sv'
    core.write_text(transform_core(core.read_text()), encoding='utf-8')
    wrapper = source / 'encoder_bus/kwt_icb_encoder.sv'
    wrapper.write_text(transform_wrapper(wrapper.read_text()), encoding='utf-8')
    vectors(out / 'vectors', dict(features=dict(lanes16=True), layout='tile'))
    testbench = out / 'input_tb.sv'
    testbench.write_text(input_bench(), encoding='utf-8')
    files = [ROOT / 'rtl/kwt_sram16x1024_model.sv', ROOT / 'rtl/kwt_spmem16.sv', ROOT / 'rtl/kwt_requantize.sv']
    files += sorted((source / 'encoder').glob('*.sv')) + sorted((source / 'encoder_bus').glob('*.sv')) + [testbench]
    records = dict(passed=False, variant='R', source=str(source.relative_to(ROOT)),
                   settings=json.loads((ROOT / 'constraints/ffn_parallel.json').read_text()),
                   scope='Local RTL and functional SRAM; normal DMA/PIO scenarios and twelve task reloads', scenarios={})

    def run(label, command):
        records['current_stage'] = label
        with (report / (label + '.log')).open('w') as log:
            subprocess.run([str(value) for value in command], cwd=str(ROOT),
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        return (report / (label + '.log')).read_text()

    try:
        run('compile', ['iverilog', '-g2012', '-DVERILATOR', '-s', 'row_reuse_tb',
                        '-I', source / 'encoder', '-o', out / 'input.vvp'] + files)
        options = dict(actual12=[], mixed_paused=['+MIXED'], single=['+SINGLE'])
        for label in args.scenarios:
            content = run(label, ['vvp', out / 'input.vvp', '+VECTOR_DIR=' + (out / 'vectors').as_posix(),
                                  '+ROW_GROUP=1', '+STREAM', '+DOUBLE'] + options[label])
            passed = ('FFN_NEXT_RTL_ALL_PASS' in content and
                      content.count('FFN_NEXT_RTL_PASS layer=') == 12 and
                      content.count('FFN_INPUT_RTL_PASS layer=') == 12)
            records['scenarios'][label] = dict(passed=passed, tasks=12, outputs_per_task=25344,
                                               ordered_trace=True, input_halves_per_task=6336,
                                               macro_reads_per_task=101376, row_slot_changes_per_task=98)
            if not passed:
                raise RuntimeError('Incomplete input scenario: ' + label)
            (report / 'result.json').write_text(json.dumps(records, indent=2))
            print('INPUT_DEVELOPMENT_PASS', label, flush=True)
        records['passed'] = True
    except Exception as error:
        records['error'] = str(error)
        raise
    finally:
        (report / 'result.json').write_text(json.dumps(records, indent=2))
        print(str(report.relative_to(ROOT)), flush=True)


if __name__ == '__main__':
    main()
