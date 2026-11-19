"""Compare AH with the SR accumulator update in the existing accelerator bench."""
import subprocess
import sys
from prepare import BUILD, REPORT, ROOT, VARIANT, dump, edit, prepare

sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'scripts/server')]
from check_ffn_sr_area_rtl_native import bench, vectors
from sr_area.observers import adapt_native_bench


def run(args, logfile):
    with logfile.open('w') as stream:
        subprocess.run(args,cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT,check=True)
    return logfile.read_text(errors='replace')


def build_bench(manifest):
    source = adapt_native_bench(bench(manifest),manifest['hardware'])
    source = source.replace('module row_reuse_tb;', 'module row_reuse_tb;\n    integer ah_soft_resets=0;', 1)
    at = source.rfind('endmodule')
    monitor = (ROOT/'tb/ffn_sr_ah/accumulator_monitor.svh').read_text()
    return source[:at] + monitor + source[at:]


def reset_bench(source):
    start = source.index('        for(layer=0;layer<12;layer=layer+1) begin\n')
    a = source.index('\n',start)+1
    b = source.index('        $display("FFN_NEXT_RTL_ALL_PASS");$finish;',a)
    body = source[a:b]
    if not body.endswith('        end\n'):
        raise RuntimeError('Unexpected task loop')
    body = body[:-len('        end\n')]
    after = source.index('    end',b)+len('    end')
    task = '    task ah_layer;\n        begin\n'+body+'        end\n    endtask\n'
    initial = """
        layer=0;
        fork : ah_reset_trial
            begin : driver
                ah_layer();
            end
            begin : resetter
                integer mac_edges;
                mac_edges=0;
                while(mac_edges<8)begin
                    @(posedge clk);
                    if(active&&dut.core.jp_mac_mask[0])mac_edges=mac_edges+1;
                end
                @(negedge clk);
                active=0;rst_n=0;icb_cmd_valid=0;icb_rsp_ready=0;
                disable ah_reset_trial.driver;
            end
        join
        repeat(4)@(negedge clk);
        rst_n=1;
        ah_layer();
        $display("AH_EXTERNAL_RESET_RELOAD_PASS");
        write_word(8'h00,32'd2);
        if(ah_soft_resets<1)$fatal(1,"AH legal idle soft reset was not seen");
        ah_layer();
        $display("AH_SOFT_RESET_RELOAD_PASS");
        $finish;
    end"""
    return task,source[:start]+initial+source[after:]


def main():
    manifest, _, candidate=prepare()
    out=BUILD/'development'
    out.mkdir(parents=True,exist_ok=True)
    vectors(out/'vectors',manifest)
    source=build_bench(manifest)
    tb=out/'ah_tb.sv'
    tb.write_text(source)
    files=[ROOT/'rtl'/x for x in ('kwt_sram16x1024_model.sv','kwt_spmem16.sv','kwt_requantize.sv')]
    files+=sorted((candidate/'encoder').glob('*.sv'))+sorted((candidate/'encoder_bus').glob('*.sv'))
    files=[str(p) for p in files]
    target=out/'verilator'
    run(['verilator_bin.exe','--cc','--exe','--main','--timing','--compiler','gcc',
         '-Wno-fatal','--top-module','row_reuse_tb','--output-split','20000','--Mdir',str(target),
         '-I'+str(candidate/'encoder')]+files+[str(tb)],REPORT/'local-elaborate.log')
    run(['mingw32-make','-C',str(target),'-f','Vrow_reuse_tb.mk',
         'VERILATOR_ROOT=E:/xpian/tools/oss-cad-suite/share/verilator',
         'PYTHON3=E:/xpian/.venv/Scripts/python.exe','-j','4'],REPORT/'local-build.log')
    args=['+VECTOR_DIR='+str(out/'vectors'),'+ROW_GROUP=2','+STREAM','+DOUBLE']
    rows=[]
    for name, opts in [('actual12',[]),('mixed_paused',['+MIXED']),('single',['+SINGLE'])]:
        result=run([str(target/'Vrow_reuse_tb.exe')]+args+opts,REPORT/('local-'+name+'.log'))
        if result.count('FFN_NEXT_RTL_PASS layer=')!=12 or 'FFN_NEXT_RTL_ALL_PASS' not in result:
            raise RuntimeError('Incomplete local scenario '+name)
        rows.append(dict(scenario=name,tasks=12,ordered_outputs=304128))
        print('AH_LOCKSTEP_PASS',name,flush=True)
    task,reset=reset_bench(source)
    index=reset.index('    initial begin')
    reset_tb=out/'ah_reset_tb.sv'
    reset_tb.write_text(reset[:index]+task+reset[index:])
    vvp=out/'ah_reset.vvp'
    run(['iverilog','-g2012','-DVERILATOR','-s','row_reuse_tb','-I',str(candidate/'encoder'),
         '-o',str(vvp)]+files+[str(reset_tb)],REPORT/'local-reset-compile.log')
    checked=run(['vvp',str(vvp)]+args,REPORT/'local-reset.log')
    if ('AH_EXTERNAL_RESET_RELOAD_PASS' not in checked or 'AH_SOFT_RESET_RELOAD_PASS' not in checked
            or checked.count('FFN_NEXT_RTL_PASS layer=')!=2):
        raise RuntimeError('Incomplete four-state reset/reload scenarios')
    dump(REPORT/'local-acceptance.json',dict(variant=VARIANT,passed=True,scenarios=rows,
        external_reset_after_mac_edges=8,soft_reset_via_mmio=True,four_state_reset_reload=True,
        comparison='pre-edge valid accumulators against SR update; sampled gated edge qualification'))
    print('AH_FOUR_STATE_RELOAD_PASS',flush=True)


if __name__=='__main__':
    main()

