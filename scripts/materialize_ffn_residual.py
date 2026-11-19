"""Independent Z/M32 edits; row-group and streaming variants use the dedicated scheduler."""
import json,re
from ffn_residual import ROOT,load,candidates,copy_tree,prove_bias32,REPORT,dump


def zero_clear(text):
    a=text.index('        if(state==CLEAR');b=text.index('        if(loading)',a)
    text=text[:a]+text[b:]
    text=re.sub(r'CLEAR: if\(clear_index==\d+\)', 'CLEAR: if(1)',text)
    text=text.replace('wire clearing=(state==CLEAR)&&(clear_index<128);',"wire clearing=1'b0;")
    return text


def bias32(text):
    # Preserve the existing two-bias capture expressions by reconstructing their bus.
    compact='compact_bias_banks' in text
    if compact:
        a=text.index('    generate for(genvar bank=0;bank<8;bank=bank+1) begin: compact_bias_banks')
        b=text.index('    wire shift_clk;',a);text=text[:a]+text[b:]
    else:
        a=text.index('        if(SPLIT_BIAS) begin: separate_bias');b=text.index('    end endgenerate',a)
        text=text[:a]+text[b:]
        text=text.replace('wire weight_clk,bias_clk;','wire weight_clk;')
        text=re.sub(r'\s*kwt_ffn_clock_gate bias_gate\([^;]+;','',text)
        text=text.replace('            assign bias_clk=clk;','')
    text=text.replace('pm_en,pm_we,bias_en,bias_we;','pm_en,pm_we;\n    reg [3:0] bias_en,bias_we;')
    text=text.replace('reg [7:0] bias_en,bias_we;','reg [3:0] bias_en,bias_we;')
    text=re.sub(r'reg \[[^\]]+\] bias_addr;', 'reg [27:0] bias_addr;',text)
    text=text.replace('pm_wdata,bias_wdata;','pm_wdata;\n    reg [63:0] bias_wdata;')
    text=re.sub(r'reg \[127:0\] bias_wdata;', 'reg [63:0] bias_wdata;',text)
    text=text.replace('pm_rdata,bias_rdata;','pm_rdata;\n    wire [16*LANES-1:0] bias_rdata;')
    text=re.sub(r'wire \[127:0\] bias_rdata;', 'wire [16*LANES-1:0] bias_rdata;',text)
    a=text.index('    wire shift_clk;')
    block='''    wire [63:0] bias32_words;
    wire [127:0] bias_pair={{32{bias32_words[63]}},bias32_words[63:32],{32{bias32_words[31]}},bias32_words[31:0]};
    assign bias_rdata=(16*LANES)'(bias_pair) << ((int'(bias_chunk)*8%LANES)*16);
    generate for(genvar bank=0;bank<4;bank=bank+1) begin: compact_bias_banks
        wire bias_clk;
        if(CLOCK_GATING) begin: gated
            kwt_ffn_clock_gate gate(.clk(clk),.enable(bias_en[bank]),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(bias_clk));
        end else assign bias_clk=clk;
        kwt_encoder_sram16x128 memory(.clk(bias_clk),.en(bias_en[bank]),.we(bias_we[bank]),
            .addr(bias_addr[bank*7+:7]),.wdata(bias_wdata[bank*16+:16]),.rdata(bias32_words[bank*16+:16]));
    end endgenerate
'''
    if compact:block=block.replace(" << ((int'(bias_chunk)*8%LANES)*16)",'')
    text=text[:a]+block+text[a:]
    text=re.sub(r'for\(b=0;b<LANES;b=b\+1\) begin pm_addr\[b\*13\+:13\]=clear_index\[12:0\];bias_addr\[b\*7\+:7\]=clear_index\[6:0\];end',
                'for(b=0;b<LANES;b=b+1) pm_addr[b*13+:13]=clear_index[12:0];\n            for(b=0;b<4;b=b+1) bias_addr[b*7+:7]=clear_index[6:0];',text)
    text=text.replace('for(b=0;b<8;b=b+1) bias_addr','for(b=0;b<4;b=b+1) bias_addr')
    a=text.index('                    address=address-16384;');b=text.index('                end else begin',a)
    text=text[:a]+'''                    address=address-16384;
                    if(address%4<2) begin
                        address=(address/4)*2+address%4;bank_index=address%4;
                        bias_en[bank_index]=1;bias_we[bank_index]=1;
                        bias_addr[bank_index*7+:7]=7'(address/4);
                        bias_wdata[bank_index*16+:16]=k==0?load_data:load_high;
                    end
'''+text[b:]
    text=re.sub(r"bias_en='1;for\(b=0;b<(LANES|8);b=b\+1\) bias_addr\[b\*7\+:7\]=7'\(int'\(bias_address\)/(LANES|8)\);",
                "bias_en='1;for(b=0;b<4;b=b+1) bias_addr[b*7+:7]=7'(int'(bias_tile)*(LANES/2)+int'(bias_chunk));",text)
    return text


def prepare(name):
    m=load(name);out=ROOT/'build/optimization/rtl_sources'/name
    copy_tree(ROOT/m['parent']['source_snapshot'],out)
    path=out/'encoder/kwt_encoder.sv';text=path.read_text();changes=m['changes']
    if changes.get('row_group') or changes.get('stream') or ('    localparam integer ROW_GROUP=' in text and (changes.get('zero_clear') or changes.get('bias32'))):
        from residual_scheduler import core,bus
        text=core(m);(out/'encoder_bus/kwt_icb_encoder.sv').write_text(bus(m))
        if m['effective_changes'].get('bias32'):prove_bias32(REPORT/(name+'-bias32-proof.json'))
    else:
        if changes.get('bias32'):
            prove_bias32(REPORT/(name+'-bias32-proof.json'));text=bias32(text)
        if changes.get('zero_clear'):text=zero_clear(text)
    path.write_text(text);dump(out/'configuration.json',m)
    return out


def variants():return {name:['PIPE','OUTPUT'] for name in candidates()}


if __name__=='__main__':
    import sys
    for name in sys.argv[1:]:print(prepare(name))
