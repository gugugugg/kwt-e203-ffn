"""Exercise RD and the frozen SR queue side by side through the normal accelerator bench."""
import subprocess
import sys
from pathlib import Path
from prepare import BUILD, QUEUE, REPORT, ROOT, VARIANT, dump, prepare

sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'scripts/server')]
from check_ffn_sr_area_rtl_native import bench, vectors
from sr_area.observers import adapt_native_bench

MONITOR = """
    wire sr_push_ready,sr_out_valid,sr_pair_valid;
    wire [15:0] sr_out_data,sr_out_high;
    wire [1:0] sr_pop;
    wire [4:0] sr_fifo;
    kwt_joint_output_queue_sr_reference sr_queue (
        .clk(Q.clk),.rst_n(Q.rst_n),.clock_test_enable(Q.clock_test_enable),
        .restart(Q.restart),.push_valid(Q.push_valid),.push_row1(Q.push_row1),
        .push_low(Q.push_low),.push_high(Q.push_high),.item(Q.item),
        .out_ready(Q.out_ready),.out_pair_ready(Q.out_pair_ready),
        .push_ready(sr_push_ready),.out_valid(sr_out_valid),.out_pair_valid(sr_pair_valid),
        .out_data(sr_out_data),.out_high(sr_out_high),.pop_count(sr_pop),.fifo_count(sr_fifo)
    );
    always @(posedge Q.clk) if(Q.rst_n) begin
        if({Q.push_ready,Q.out_valid,Q.out_pair_valid,Q.pop_count,Q.fifo_count} !==
           {sr_push_ready,sr_out_valid,sr_pair_valid,sr_pop,sr_fifo})
            $fatal(1,"RD handshake differs item=%0d",Q.item);
        if((sr_out_valid && Q.out_data !== sr_out_data) ||
           (sr_pair_valid && Q.out_high !== sr_out_high))
            $fatal(1,"RD valid output differs item=%0d",Q.item);
        if(Q.issue_count !== sr_queue.issue_count)
            $fatal(1,"RD pending reservation differs item=%0d",Q.item);
    end
    generate for(genvar rd_bank=0;rd_bank<3;rd_bank++) begin: rd_compare
        always @(posedge Q.clk) if(Q.rst_n) begin
            if({Q.row_stash[rd_bank].en,Q.row_stash[rd_bank].we} !==
               {sr_queue.row_stash[rd_bank].en,sr_queue.row_stash[rd_bank].we})
                $fatal(1,"RD macro operation differs bank=%0d item=%0d",rd_bank,Q.item);
            if(sr_queue.row_stash[rd_bank].en &&
               (Q.row_stash[rd_bank].address !== sr_queue.row_stash[rd_bank].address ||
                (sr_queue.row_stash[rd_bank].we &&
                 Q.row_stash[rd_bank].data !== sr_queue.row_stash[rd_bank].data)))
                $fatal(1,"RD macro transaction differs bank=%0d item=%0d",rd_bank,Q.item);
        end
    end endgenerate
""".replace('Q.', 'dut.core.output_queue.')


def main():
    manifest, source, candidate = prepare()
    out = BUILD / 'development'
    out.mkdir(parents=True, exist_ok=True)
    reference = out / 'sr_queue_reference.sv'
    reference.write_text((source / QUEUE).read_text().replace(
        'module kwt_joint_output_queue(', 'module kwt_joint_output_queue_sr_reference(', 1))
    text = adapt_native_bench(bench(manifest), manifest['hardware'])
    at = text.rfind('endmodule')
    tb = out / 'rd_tb.sv'
    tb.write_text(text[:at] + MONITOR + text[at:])
    vectors(out / 'vectors', manifest)
    files = [ROOT / 'rtl' / file for file in ('kwt_sram16x1024_model.sv', 'kwt_spmem16.sv', 'kwt_requantize.sv')]
    files += sorted((candidate / 'encoder').glob('*.sv')) + sorted((candidate / 'encoder_bus').glob('*.sv'))
    target = out / 'verilator'
    with (REPORT / 'local-compile.log').open('w') as log:
        subprocess.run(['verilator_bin.exe','--cc','--exe','--main','--timing','--compiler','gcc',
            '-Wno-fatal','--top-module','row_reuse_tb','--output-split','20000','--Mdir',str(target),
            '-I'+str(candidate/'encoder')] + [str(p) for p in files + [reference, tb]],
            cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['mingw32-make','-C',str(target),'-f','Vrow_reuse_tb.mk',
            'VERILATOR_ROOT=E:/xpian/tools/oss-cad-suite/share/verilator',
            'PYTHON3=E:/xpian/.venv/Scripts/python.exe','-j','4'],
            cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    rows = []
    for scenario, options in [('actual12', []), ('mixed_paused', ['+MIXED']), ('single', ['+SINGLE'])]:
        path = REPORT / ('local-' + scenario + '.log')
        with path.open('w') as log:
            subprocess.run([str(target/'Vrow_reuse_tb.exe'),'+VECTOR_DIR='+str(out/'vectors'),
                '+ROW_GROUP=2','+STREAM','+DOUBLE'] + options,
                cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, check=True)
        text = path.read_text()
        if text.count('FFN_NEXT_RTL_PASS layer=') != 12 or 'FFN_NEXT_RTL_ALL_PASS' not in text:
            raise RuntimeError('Incomplete normal scenario ' + scenario)
        rows.append(dict(scenario=scenario, tasks=12, ordered_outputs=12*25344))
        print('RD_LOCKSTEP_PASS', scenario, flush=True)
    dump(REPORT/'local-acceptance.json',dict(variant=VARIANT,passed=True,
        scenarios=rows, comparison='per-clock handshake, enabled SRAM transactions, and valid return against SR'))


if __name__ == '__main__':
    main()

