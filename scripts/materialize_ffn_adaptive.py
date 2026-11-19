"""Apply one recorded change to an independently frozen parent snapshot."""
import json
import re
from ffn_adaptive import ROOT,load,copy_tree,clear_depth


def replace_required(text,old,new):
    if old not in text:raise RuntimeError('Frozen source does not contain the expected edit: '+old[:100])
    return text.replace(old,new)


def compact_bias(text):
    text=replace_required(text,'reg [LANES-1:0] pm_en,pm_we,bias_en,bias_we;',
        'reg [LANES-1:0] pm_en,pm_we;\n    reg [7:0] bias_en,bias_we;')
    text=replace_required(text,'reg [7*LANES-1:0] bias_addr;','reg [55:0] bias_addr;')
    text=replace_required(text,'reg [16*LANES-1:0] pm_wdata,bias_wdata;',
        'reg [16*LANES-1:0] pm_wdata;\n    reg [127:0] bias_wdata;')
    text=replace_required(text,'wire [16*LANES-1:0] pm_rdata,bias_rdata;',
        'wire [16*LANES-1:0] pm_rdata;\n    wire [127:0] bias_rdata;')
    text=replace_required(text,'wire weight_clk,bias_clk;','wire weight_clk;')
    text=replace_required(text,'''            kwt_ffn_clock_gate bias_gate(.clk(clk),.enable(bias_en[bank]),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(bias_clk));''','')
    text=replace_required(text,'            assign bias_clk=clk;','')
    start=text.index('        if(SPLIT_BIAS) begin: separate_bias')
    stop=text.index('    end endgenerate',start)
    text=text[:start]+text[stop:]
    at=text.index('    wire shift_clk;')
    text=text[:at]+'''    generate for(genvar bank=0;bank<8;bank=bank+1) begin: compact_bias_banks
        wire bias_clk;
        if(CLOCK_GATING) begin: gated
            kwt_ffn_clock_gate gate(.clk(clk),.enable(bias_en[bank]),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(bias_clk));
        end else assign bias_clk=clk;
        kwt_encoder_sram16x128 memory(.clk(bias_clk),.en(bias_en[bank]),.we(bias_we[bank]),
            .addr(bias_addr[bank*7+:7]),.wdata(bias_wdata[bank*16+:16]),.rdata(bias_rdata[bank*16+:16]));
    end endgenerate
'''+text[at:]
    text=replace_required(text,'for(b=0;b<LANES;b=b+1) begin pm_addr[b*13+:13]=clear_index[12:0];bias_addr[b*7+:7]=clear_index[6:0];end',
        'for(b=0;b<LANES;b=b+1) pm_addr[b*13+:13]=clear_index[12:0];\n            for(b=0;b<8;b=b+1) bias_addr[b*7+:7]=clear_index[6:0];')
    text=replace_required(text,'address=address-16384;bank_index=address%LANES;',
        'address=address-16384;bank_index=address%8;')
    text=replace_required(text,"bias_addr[bank_index*7+:7]=7'(address/LANES);","bias_addr[bank_index*7+:7]=7'(address/8);")
    text=replace_required(text,"bias_en='1;for(b=0;b<LANES;b=b+1) bias_addr[b*7+:7]=7'(int'(bias_address)/LANES);",
        "bias_en='1;for(b=0;b<8;b=b+1) bias_addr[b*7+:7]=7'(int'(bias_address)/8);")
    text=replace_required(text,"(int'(bias_chunk)*8%LANES)*16",'0')
    return text


def prepare(variant):
    m=load(variant);f=m['features'];changes=m['changes'];effective=m.get('effective_changes',changes)
    out=ROOT/'build/optimization/rtl_sources'/variant
    copy_tree(ROOT/m['parent']['source_snapshot'],out)
    path=out/'encoder/kwt_encoder.sv';text=path.read_text()
    if changes.get('compact_bias'):
        if not f['lanes16'] or not f['split_bias']:raise RuntimeError('Compact bias candidate requires the split sixteen-lane parent')
        text=compact_bias(text)
    if changes.get('trim_clear'):
        text=replace_required(text,'clear_index==8193','clear_index==%d'%(clear_depth(f)-1))
    if changes.get('quiet_reset'):
        text=replace_required(text,'if(state==CLEAR) begin','if(state==CLEAR&&rst_n) begin')
    if changes.get('fine_memory_gate'):
        memory=out/'encoder/kwt_encoder_memory.sv';s=memory.read_text()
        s=re.sub(r'\s*wire bank_clk;\s*kwt_ffn_clock_gate gate\([^;]+;', '', s)
        s=s.replace('.clk(bank_clk)', '.clk(clk)')
        s=s.replace('input wire clk,','input wire clk,test_enable,')
        s=s.replace('kwt_spmem16 #','kwt_adaptive_spmem16 #').replace('.clk(clk),.en(en[b])','.clk(clk),.test_enable(test_enable),.en(en[b])')
        memory.write_text(s)
        copy_tree_file=ROOT/'rtl/ffn/kwt_adaptive_spmem16.sv'
        (out/'encoder/kwt_adaptive_spmem16.sv').write_text(copy_tree_file.read_text())
        text=text.replace('kwt_spmem16 #','kwt_adaptive_spmem16 #')
        text=text.replace('.clk(weight_clk),.en(pm_en[bank])','.clk(weight_clk),.test_enable(clock_test_enable),.en(pm_en[bank])')
        text=text.replace('.clk(clk),.en(sp_en)','.clk(clk),.test_enable(clock_test_enable),.en(sp_en)')
        text=text.replace('if(CLOCK_GATING) begin: gated','if(1) begin: gated').replace('if(CLOCK_GATING) begin: gate_shift','if(1) begin: gate_shift')
        text=replace_required(text,'''            kwt_ffn_clock_gate weight_gate(.clk(clk),.enable(pm_en[bank]),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(weight_clk));''','            assign weight_clk=clk;')
    if changes.get('fine_register_gate'):
        a=text.index('    wire datapath_clk;');b=text.index('    wire [6:0] read_row=',a)
        text=text[:a]+text[b:]
        a=text.index('    integer di;');b=text.rfind('endmodule')
        offset='0' if effective.get('compact_bias') else "(int'(bias_chunk)*8%LANES)*16"
        datapath='''    wire datapath_clk=clk;
    generate for(genvar group_id=0;group_id<GROUPS;group_id=group_id+1) begin: fine_accumulators
        wire bias_update=bias_capture&&((OVERLAP?int'(prep_group):0)==group_id);
        wire mac_update=(state==B_MAC)&&((OVERLAP?int'(compute_group):0)==group_id);
        wire acc_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(bias_update||mac_update),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(acc_clk));
        for(genvar lane_id=0;lane_id<LANES;lane_id=lane_id+1) begin: lane_registers
            always @(posedge acc_clk or negedge rst_n) begin
                if(!rst_n) begin
                    accumulator[group_id*LANES+lane_id]<=0;
                    shifts[group_id*LANES+lane_id]<=0;
                end else begin
                    if(bias_update&&int'(bias_chunk)==lane_id/2) begin
                        accumulator[group_id*LANES+lane_id]<=36'($signed(bias_rdata[OFFSET+(lane_id%2)*64+:64]));
                        shifts[group_id*LANES+lane_id]<=$signed(shift_rdata[(lane_id%2)*8+:8]);
                    end
                    if(mac_update)
                        accumulator[group_id*LANES+lane_id]<=accumulator[group_id*LANES+lane_id]+36'(mac_a*$signed(pm_rdata[lane_id*16+:16]));
                end
            end
        end
    end endgenerate
    wire fifo_clk;
    kwt_ffn_clock_gate fifo_gate(.clk(clk),.enable(fifo_push),
        .test_enable(clock_test_enable||!rst_n),.gated_clk(fifo_clk));
    always @(posedge fifo_clk) if(fifo_push) fifo[fifo_write]<=result_word;
'''.replace('OFFSET',offset)
        text=text[:a]+datapath+text[b:]
    if changes.get('fifo64'):
        for old,new in [('fifo[0:15]','fifo[0:63]'),('reg [3:0] fifo_write,fifo_read','reg [5:0] fifo_write,fifo_read'),
                        ('reg [4:0] fifo_count','reg [6:0] fifo_count'),('fifo_count<16','fifo_count<64'),
                        ("wire [3:0] next_read=fifo_read+4'd1", "wire [5:0] next_read=fifo_read+6'd1"),
                        ("fifo_read+4'(pop_count)","fifo_read+6'(pop_count)"),
                        ("fifo_count+5'(fifo_push)-5'(pop_count)","fifo_count+7'(fifo_push)-7'(pop_count)")]:
            text=replace_required(text,old,new)
    if changes.get('fast_response'):
        from ffn_fast_response import apply
        adapter=out/'encoder_bus/kwt_icb_encoder.sv';adapter.write_text(apply(adapter.read_text()))
    path.write_text(text)
    (out/'configuration.json').write_text(json.dumps(m,indent=2))
    return out


def variants():
    from ffn_adaptive import candidates
    return {name:['PIPE','OUTPUT'] for name in candidates()}


if __name__=='__main__':
    import sys
    for variant in sys.argv[1:]:print(prepare(variant))
