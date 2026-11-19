"""Observe initialized shift data at the legal consume edge."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c_area import observers as prior


def shift_observer(core, window, reset, hardware):
    index = 'lane_id%16' if 'SS' in hardware else 'lane_id'
    block = """
`ifndef KWT_UNIFIED_GATE
    generate for(genvar lane_id=0;lane_id<32;lane_id=lane_id+1)begin: ara_shift_lifecycle
        reg has_shift=0;
        reg signed [7:0] shift_at_seed;
        always @(posedge CORE.clk or negedge RESET)begin
            if(!RESET)has_shift=0;
            else if(CORE.layer_start_valid&&CORE.layer_start_ready)has_shift=0;
            else if(WINDOW)begin
                if(CORE.jp_quant_mask[lane_id])begin
                    if(!has_shift || (^CORE.shifts[INDEX]===1'bx) || CORE.shifts[INDEX]!==shift_at_seed)
                        $fatal(1,"ARA_SHIFT_CONSUMPTION lane=%0d row=%0d tile=%0d shift=%h expected=%h",
                            lane_id,CORE.row,CORE.tile,CORE.shifts[INDEX],shift_at_seed);
                    has_shift=0;
                end
                if(CORE.jp_seed_mask[lane_id])begin
                    shift_at_seed=$signed(CORE.jp_shift_return[(lane_id%2)*8+:8]);
                    has_shift=1;
                end
            end
        end
    end endgenerate
`endif
"""
    return block.replace('CORE',core).replace('WINDOW',window).replace('RESET',reset).replace('INDEX',index)


def commit_observer(core,window,reset,hardware=None):
    return prior.commit_observer(core,window,reset,hardware)+shift_observer(core,window,reset,hardware or [])


def adapt_native_bench(text,hardware=None):
    text=prior.adapt_native_bench(text,hardware)
    at=text.rfind('endmodule')
    return text[:at]+shift_observer('dut.core','active','dut.core.rst_n',hardware or [])+text[at:]


def adapt_cpu_bench(text,core,hardware=None):
    text=prior.adapt_cpu_bench(text,core,hardware)
    at=text.rfind('endmodule')
    return text[:at]+shift_observer(core,'activity_window',core+'.rst_n',hardware or [])+text[at:]
