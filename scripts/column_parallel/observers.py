"""32-lane commit, return-copy and ordered-pair observers for the unchanged interface."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server'))
import logic_power_observers as previous


def commit_observer(core, window, reset):
    text = previous.commit_observer(core, ['M2'], window, reset)
    text = text.replace('jp_lane<16', 'jp_lane<32').replace(core+'.lane[2:1]', core+'.lane[3:1]')
    return text + '''
`ifndef KWT_UNIFIED_GATE
    generate for(genvar cp_row=0;cp_row<2;cp_row=cp_row+1)begin: cp_hold_rows
        reg issued=0;
        always @(posedge CORE.clk)issued<=RESET&&CORE.ap_input_rows[cp_row].read_enable;
        for(genvar cp_copy=0;cp_copy<2;cp_copy=cp_copy+1)begin: copies
            always @(negedge CORE.clk)if(RESET&&WINDOW&&issued)
                if(CORE.jp_input_return[(cp_row*2+cp_copy)*16+:16]!==CORE.ap_input_rdata[cp_row*16+:16])
                    $fatal(1,"COLUMN_PARALLEL_RETURN row=%0d copy=%0d",cp_row,cp_copy);
        end
    end endgenerate
`endif
'''.replace('CORE',core).replace('WINDOW',window).replace('RESET',reset)


def adapt_native_bench(text):
    text = previous.adapt_native_bench(text, ['M2'])
    old = previous.commit_observer('dut.core', ['M2'], 'active', 'dut.core.rst_n')
    return text.replace(old, commit_observer('dut.core', 'active', 'dut.core.rst_n'), 1)


def adapt_cpu_bench(text, core):
    text = previous.adapt_cpu_bench(text, core, ['M2'])
    old = previous.commit_observer(core, ['M2']).replace('`ifndef KWT_UNIFIED_GATE\n','').replace('`endif\n','').strip('\n')
    new = commit_observer(core, 'activity_window', 'rst_n').replace('`ifndef KWT_UNIFIED_GATE\n','').replace('`endif\n','').strip('\n')
    return text.replace(old, new, 1)
