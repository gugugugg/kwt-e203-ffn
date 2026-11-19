"""Derive the independent CH accumulator and predictor candidates."""
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[2]
PARENT = 'ffn_sysbus32_lossless'
ROUND = 'ffn_ch_efficiency'
CANDIDATES = {'AG': 'ffn_che_AG', 'PR': 'ffn_che_PR'}
SOC = ROOT / 'build/optimization/complete_soc'
RTL = ROOT / 'build/optimization/rtl_sources'
REPORT = ROOT / 'reports/optimization' / ROUND


def replace(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def accumulator(text):
    text = replace(text, '        for(genvar row=0;row<4;row=row+1) begin: lanes', '''        wire execute_tail=tags[AGE+1].tail;
        wire [1:0] acc_write={execute&&context_select,execute&&!context_select};
        wire [1:0] acc_clock, fourth_clock;
        for(genvar ctx=0;ctx<2;ctx=ctx+1) begin: accum_clocks
            kwt_ffn_clock_gate group_gate(.clk(clk),.enable(acc_write[ctx]),
                .test_enable(1'b0),.gated_clk(acc_clock[ctx]));
            kwt_ffn_clock_gate fourth_gate(.clk(clk),.enable(acc_write[ctx]&&!execute_tail),
                .test_enable(1'b0),.gated_clk(fourth_clock[ctx]));
        end
        for(genvar row=0;row<4;row=row+1) begin: lanes''')
    return replace(text, '''            wire lane_enable=execute&&(row!=3||!tags[AGE+1].tail);
            always @(posedge clk) begin
                if(lane_enable&&!context_select) acc_a<=sum;
                if(lane_enable&&context_select) acc_b<=sum;
            end''', '''            wire clk_a=(row==3)?fourth_clock[0]:acc_clock[0];
            wire clk_b=(row==3)?fourth_clock[1]:acc_clock[1];
            always @(posedge clk_a) acc_a<=sum;
            always @(posedge clk_b) acc_b<=sum;''')


def predictor(text):
    text = replace(text, '    reg [15:0] row7 [0:63];', '    wire [15:0] predicted_row7;')
    assert text.count('row7[inner]') == 3
    text = replace(text, '                    if (index<6144 && input_lane==7) row7[inner]<=value[15:0];\n', '')
    text = text.replace('row7[inner]', 'predicted_row7')
    return replace(text, '    wire push = decode && last_symbol;', '''    if (INPUT_PACKET) begin: predictor_memory
        wire fire=rst_n&&!restart&&decode;
        wire rd=fire&&((index>=13'd510&&index<13'd6144&&input_lane==6)||
                      (index>=13'd6144&&tail_lane==1&&inner!=6'd63));
        wire wr=fire&&index>=13'd8&&index<=13'd6144&&input_lane==0;
        wire [5:0] address=wr ? inner-6'd1 : inner+6'd1;
        // Lane 0 uses the prefetched Q while the previous lane 7 value is written.
        RAMSP128X16 memory(.CLK(clk),.CEN(!(rd||wr)),.GWEN(!wr),.WEN({16{!wr}}),
            .A({1'b0,address}),.D(prev),.Q(predicted_row7),.EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
    end else begin: no_predictor_memory
        assign predicted_row7=0;
    end
    wire push = decode && last_symbol;''')


def trace_bench(text):
    return replace(text, '    always @(posedge clk) if(rst_n) begin', '''`ifndef KWT_UNIFIED_GATE
    integer bus_trace=0;
    initial begin
        string file_name;
        if($value$plusargs("BUS_TRACE=%s",file_name)) begin
            bus_trace=$fopen(file_name,"w");
            if(!bus_trace) $fatal(1,"Cannot open BUS_TRACE");
        end
    end
    always @(posedge clk) if(bus_trace) begin
      if(activity_window) begin
        if(dut.shared_memory.memory.en) begin
            if(dut.shared_memory.memory.we)
                $fdisplay(bus_trace,"W %0d %05h %1h %08h",cycles-start_cycle,
                    dut.shared_memory.memory.addr,dut.shared_memory.memory.wmask,dut.shared_memory.memory.wdata);
            else $fdisplay(bus_trace,"R %0d %05h",cycles-start_cycle,dut.shared_memory.memory.addr);
        end
        if(dut.sysmem_icb_rsp_valid&&dut.sysmem_icb_rsp_ready) begin
            $fdisplay(bus_trace,"T %0d %1h %08h",cycles-start_cycle,dut.sysmem_icb_rsp_err,dut.sysmem_icb_rsp_rdata);
        end
      end
      if((activity_window||ld_dma_writes==12672)&&result_ack)
          $fdisplay(bus_trace,"A %0d",cycles-start_cycle);
    end
    final if(bus_trace) $fclose(bus_trace);
`endif
    always @(posedge clk) if(rst_n) begin''')


def build(kind):
    variant = CANDIDATES[kind]
    enc = RTL / variant / 'encoder'
    enc.mkdir(parents=True, exist_ok=True)
    changed = 'kwt_threebank_core.sv' if kind == 'AG' else 'decode.sv'
    transform = accumulator if kind == 'AG' else predictor
    for path in (RTL / PARENT / 'encoder').glob('*.sv'):
        target = enc / path.name
        if path.name == changed:
            target.write_text(transform(path.read_text()), encoding='utf-8')
        else:
            shutil.copyfile(path, target)
    frozen = SOC / PARENT
    dest = SOC / variant
    for path in list(frozen.iterdir()) + list((frozen/'eda').glob('*.tcl')):
        if not path.is_file() or path.suffix not in ('.v', '.sv', '.svh', '.f', '.json', '.tcl', '.rcf'):
            continue
        target = dest / path.relative_to(frozen)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        renamed = data.replace(PARENT.encode(), variant.encode())
        if path.name == 'complete_soc_tb.sv':
            renamed = trace_bench(renamed.decode().replace('\r\n','\n')).encode()
        if kind == 'AG' and path.name in ('files.f', 'synthesis_files.f'):
            renamed += b'rtl/ffn/kwt_ffn_clock_gate.sv\n'
        target.write_bytes(renamed)
    packed = dest / 'packed_inputs'
    packed.mkdir(exist_ok=True)
    for path in (frozen/'packed_inputs').glob('*.hex'):
        shutil.copyfile(path, packed/path.name)
    assert len(list(packed.glob('*.hex'))) == 36
    print('CH_DERIVED', variant, changed, flush=True)


if __name__ == '__main__':
    for kind in sys.argv[1:] or ('AG', 'PR'):
        build(kind)
