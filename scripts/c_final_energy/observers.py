"""Observe current-row shift consumption and physical single-head queue bypass."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c_energy import observers as previous

def mechanism(core,window,reset,kind):
    if kind=='SS':
        text='''
`ifndef KWT_UNIFIED_GATE
    generate for(genvar ss_lane=0;ss_lane<32;ss_lane=ss_lane+1)begin: ss_consumption_observer
        reg signed [7:0] reference_shift=0;
        always @(posedge CORE.clk or negedge RESET)begin
            if(!RESET)reference_shift=0;
            else if(WINDOW)begin
                if(CORE.jp_quant_mask[ss_lane] && CORE.shifts[ss_lane%16]!==reference_shift)
                    $fatal(1,"SS_SHIFT_CONSUMPTION lane=%0d row=%0d tile=%0d",ss_lane,CORE.row,CORE.tile);
                if(CORE.jp_seed_mask[ss_lane])reference_shift=$signed(CORE.jp_shift_return[(ss_lane%2)*8+:8]);
            end
        end
    end endgenerate
`endif
'''
    elif kind=='O1':
        text='''
`ifndef KWT_UNIFIED_GATE
    integer cfe_bypasses=0;
    always @(posedge CORE.clk or negedge RESET)begin
        if(!RESET)cfe_bypasses=0;
        else if(WINDOW)begin
            if(CORE.output_queue.bypass)begin
                cfe_bypasses=cfe_bypasses+1;
                if(CORE.output_queue.drain0 || CORE.output_queue.read0 || CORE.output_queue.read1)
                    $fatal(1,"O1_PORT_EXCLUSION");
            end
            if(CORE.output_queue.fifo_count>16 || CORE.output_queue.held_count+CORE.output_queue.pending_count>2)
                $fatal(1,"O1_QUEUE_CAPACITY");
        end
    end
`endif
'''
    else:text=''
    return text.replace('CORE',core).replace('WINDOW',window).replace('RESET',reset)

def commit_observer(core,window,reset,kind):
    return previous.commit_observer(core,window,reset)+mechanism(core,window,reset,kind)

def adapt_native_bench(text,hardware=None):
    text=previous.adapt_native_bench(text)
    kind='SS' if 'SS' in (hardware or []) else 'O1'
    old=previous.commit_observer('dut.core','active','dut.core.rst_n')
    return text.replace(old,commit_observer('dut.core','active','dut.core.rst_n',kind),1)

def adapt_cpu_bench(text,core,hardware=None):
    text=previous.adapt_cpu_bench(text,core)
    kind='SS' if 'SS' in (hardware or []) else 'O1'
    old=previous.commit_observer(core,'activity_window','rst_n').replace('`ifndef KWT_UNIFIED_GATE\n','').replace('`endif\n','').strip('\n')
    new=commit_observer(core,'activity_window','rst_n',kind).replace('`ifndef KWT_UNIFIED_GATE\n','').replace('`endif\n','').strip('\n')
    return text.replace(old,new,1)
