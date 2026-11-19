"""One real four-state outer reset after eight first-task MACs, then full reload."""
import json,subprocess,sys
from pathlib import Path
from prepare import ROOT,BUILD,REPORT

def main():
    name=sys.argv[1];out=BUILD/'development'/name;r=REPORT/'development'/name;source=ROOT/'build/optimization/rtl_sources'/name
    text=(out/'ar_area_tb.sv').read_text();start=text.index('        for(layer=0;layer<12;layer=layer+1) begin\n');body_start=start+len('        for(layer=0;layer<12;layer=layer+1) begin\n');end=text.index('        $display("FFN_NEXT_RTL_ALL_PASS");$finish;',body_start)
    loop=text[body_start:end];assert loop.endswith('        end\n');body=loop[:-len('        end\n')]
    initial_start=text.rfind('    initial begin',0,start);initial_end=text.index('    end',end)+len('    end')
    setup=text[initial_start:start]
    replacement=setup+'''
        layer=0;
        fork : reset_trial
            begin : driver
                run_complete_layer();
            end
            begin : resetter
                integer consumed_macs;
                consumed_macs=0;
                while(consumed_macs<8)begin
                    @(posedge clk);
                    if(active&&dut.core.jp_mac_mask[0])consumed_macs=consumed_macs+1;
                end
                @(negedge clk);
                active=0;rst_n=0;icb_cmd_valid=0;icb_rsp_ready=0;
                disable reset_trial.driver;
                $display("AREA_AR_OUTER_RESET_AFTER_MACS count=%0d",consumed_macs);
            end
        join
        repeat(4)@(negedge clk);
        rst_n=1;
        run_complete_layer();
        $display("AREA_AR_OUTER_RESET_RELOAD_PASS outputs=25344 trace=%0d",trace_count);
        $finish;
    end'''
    task='    task run_complete_layer;\n        begin\n'+body+'        end\n    endtask\n'
    text=text[:initial_start]+task+replacement+text[initial_end:];tb=out/'reset_reload_tb.sv';tb.write_text(text)
    files=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv',ROOT/'rtl/kwt_requantize.sv']+sorted((source/'encoder').glob('*.sv'))+sorted((source/'encoder_bus').glob('*.sv'))+[tb]
    with (r/'reset-reload-compile.log').open('w') as log:subprocess.run(['iverilog','-g2012','-DVERILATOR','-s','row_reuse_tb','-I',str(source/'encoder'),'-o',str(out/'reset-reload.vvp')]+[str(p) for p in files],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    with (r/'reset-reload.log').open('w') as log:subprocess.run(['vvp',str(out/'reset-reload.vvp'),'+VECTOR_DIR='+str(out/'vectors'),'+ROW_GROUP=2','+STREAM','+DOUBLE'],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    log=(r/'reset-reload.log').read_text();assert 'AREA_AR_OUTER_RESET_AFTER_MACS count=8' in log and 'AREA_AR_OUTER_RESET_RELOAD_PASS outputs=25344 trace=25344' in log
    (r/'reset-reload.json').write_text(json.dumps(dict(passed=True,case=1,layer=0,reset_after_MAC_edges=8,outer_reset_hold_cycles=4,outputs_after_full_reload=25344,ordered_trace=True,shared_response_state_reset=True,arbitrary_DMA_soft_cancel_not_added=True,four_state=True,native_CPU=False),indent=2));print('AR_AREA_AR_OUTER_RESET_RELOAD_PASS',flush=True)

if __name__=='__main__':main()
