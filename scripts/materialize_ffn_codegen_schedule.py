"""Apply one independent change to an immutable accepted source snapshot."""
import re
from ffn_codegen_schedule import ROOT, REPORT, load, candidates, copy_tree, dump, prove_bias32


def replace(text, before, after, count=1):
    actual = text.count(before)
    if actual != count:
        raise RuntimeError('Inspect frozen RTL before applying this change: %r (%d matches)' % (before[:90], actual))
    return text.replace(before, after)


def schedule(text, pipelined=False, early=False):
    request = 'wire bias_request=state==BIAS_REQ,bias_capture=state==BIAS_CAP;'
    signals = '''localparam CG_PIPE=%d, CG_EARLY=%d;
    reg [3:0] cg_issue_chunk;
    reg [2:0] cg_return_chunk;
    reg cg_pending,cg_seeded;
    wire cg_next=(row<98)||(tile<TILES-1);
    wire cg_emit_request=CG_EARLY&&(state==EMIT)&&fifo_push&&!lane[0]&&cg_next;
    wire cg_emit_capture=CG_EARLY&&(state==EMIT)&&fifo_push&&lane[0]&&cg_next;
    wire [3:0] cg_request_tile=cg_emit_request?4'((tile==TILES-1)?0:tile+1):4'(tile);
    wire [2:0] cg_capture_chunk=cg_emit_capture?3'(lane/2):(CG_PIPE?cg_return_chunk:3'(chunk));
    wire [2:0] cg_request_chunk=cg_emit_request?3'(lane/2):(CG_PIPE?cg_issue_chunk[2:0]:3'(chunk));
    wire cg_prep_request=(state==BIAS_REQ)||(CG_PIPE&&(state==BIAS_CAP)&&(cg_issue_chunk<8));
    wire bias_request=cg_prep_request||cg_emit_request;
    wire bias_capture=(CG_PIPE?cg_pending:(state==BIAS_CAP))||cg_emit_capture;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin cg_issue_chunk<=0;cg_return_chunk<=0;cg_pending<=0;cg_seeded<=0;end
        else begin
            cg_pending<=CG_PIPE&&cg_prep_request;
            if(state==MAC_INIT)cg_issue_chunk<=0;
            else if(CG_PIPE&&cg_prep_request)begin cg_return_chunk<=cg_issue_chunk[2:0];cg_issue_chunk<=cg_issue_chunk+1'b1;end
            if(layer_start_valid&&layer_start_ready)cg_seeded<=0;
            else if(cg_emit_capture&&lane==LANES-1)cg_seeded<=1;
        end
    end
    ''' % (int(pipelined), int(early))
    text = replace(text, request, signals)
    text = replace(text, 'wire [15:0] bias_address=16\'(tile*LANES*4+chunk*8);',
                   "wire [15:0] bias_address=16'(int'(cg_request_tile)*LANES*4+int'(cg_request_chunk)*8);")
    text = text.replace('bias_capture&&chunk==', 'bias_capture&&cg_capture_chunk==')
    text = text.replace('bias_update&&chunk==', 'bias_update&&cg_capture_chunk==')
    text = text.replace('capture=bias_capture&&(chunk==shift_bank)', 'capture=bias_capture&&(cg_capture_chunk==shift_bank)')
    text = replace(text, 'BIAS32?(tile*(LANES/2)+chunk)', "BIAS32?(int'(cg_request_tile)*(LANES/2)+int'(cg_request_chunk))")
    text = replace(text, "shift_addr=7'(tile*(LANES/2)+chunk);", "shift_addr=7'(int'(cg_request_tile)*(LANES/2)+int'(cg_request_chunk));")
    old = 'BIAS_CAP:if(chunk==LANES/2-1) begin inner<=0;mac_group<=0;state<=A_REQ;end else begin chunk<=chunk+1;state<=BIAS_REQ;end'
    new = '''BIAS_CAP:if(CG_PIPE)begin
                    if(cg_pending&&cg_return_chunk==7)begin inner<=0;mac_group<=0;state<=A_REQ;end
                end else if(chunk==LANES/2-1) begin inner<=0;mac_group<=0;state<=A_REQ;end else begin chunk<=chunk+1;state<=BIAS_REQ;end'''
    text = replace(text, old, new)
    if pipelined:
        text = replace(text, 'wire [127:0] bias_pair;', 'wire [127:0] cg_macro_bias_pair;')
        text = replace(text, 'assign bias_pair=', 'assign cg_macro_bias_pair=', count=2)
        text = replace(text, 'wire [15:0] shift_rdata;', '''wire [15:0] cg_macro_shift_rdata;
    reg [127:0] cg_bias_return;
    reg [15:0] cg_shift_return;
    // Hold the returned word across the next synchronous macro read edge.
    always @(negedge clk) if(cg_pending) begin
        cg_bias_return<=cg_macro_bias_pair;
        cg_shift_return<=cg_macro_shift_rdata;
    end
    wire [127:0] bias_pair=cg_emit_capture?cg_macro_bias_pair:cg_bias_return;
    wire [15:0] shift_rdata=cg_emit_capture?cg_macro_shift_rdata:cg_shift_return;''')
        text = replace(text, '.rdata(shift_rdata));', '.rdata(cg_macro_shift_rdata));')
    if early:
        text = replace(text, 'WAIT_INPUT:if(input_complete) state<=MAC_INIT;', 'WAIT_INPUT:if(input_complete)begin inner<=0;state<=cg_seeded?A_REQ:MAC_INIT;end')
        # Only the row-zero EMIT transition changes; generic unreachable stash states remain untouched.
        a = text.index('                EMIT:if(fifo_push)')
        b = text.index('                EMIT_STASH:', a)
        emit = text[a:b]
        emit = replace(emit, 'tile<=tile+1;state<=MAC_INIT;', 'tile<=tile+1;inner<=0;state<=A_REQ;')
        text = text[:a] + emit + text[b:]
    return text


def booth(text):
    block = '''    wire [7:0] cg_one,cg_two,cg_negative;
    generate for(genvar digit=0;digit<8;digit=digit+1)begin: cg_activation_decode
        wire [16:0] extended_activation={mac_a[15:0],1'b0};
        wire low=extended_activation[2*digit];
        wire middle=extended_activation[2*digit+1],high=extended_activation[2*digit+2];
        assign cg_one[digit]=middle^low;
        assign cg_two[digit]=!(middle^low)&&(high^middle);
        assign cg_negative[digit]=high;
    end endgenerate
    wire signed [35:0] cg_product[0:LANES-1];
    generate for(genvar mul_lane=0;mul_lane<LANES;mul_lane=mul_lane+1)begin: cg_booth_lanes
        wire signed [17:0] w={{2{pm_rdata[mul_lane*16+15]}},pm_rdata[mul_lane*16+:16]};
        wire signed [35:0] term[0:7];
        for(genvar digit=0;digit<8;digit=digit+1)begin: digits
            wire signed [17:0] magnitude=cg_one[digit]?w:(cg_two[digit]?(w<<<1):18'sd0);
            wire signed [17:0] partial=cg_negative[digit]?-magnitude:magnitude;
            assign term[digit]=$signed({{18{partial[17]}},partial})<<<(digit*2);
        end
        assign cg_product[mul_lane]=term[0]+term[1]+term[2]+term[3]+term[4]+term[5]+term[6]+term[7];
    end endgenerate
'''
    text = replace(text, '    wire [35:0] quant_bits=', block + '    wire [35:0] quant_bits=')
    return replace(text, "36'(mac_a*$signed(pm_rdata[lane_id*16+:16]))", 'cg_product[lane_id]')


def split_accumulator(text):
    text = replace(text, 'reg signed [35:0] accumulator[0:ROW_GROUP*LANES-1];', '''wire signed [35:0] accumulator[0:ROW_GROUP*LANES-1];
    reg [17:0] cg_low[0:ROW_GROUP*LANES-1],cg_high[0:ROW_GROUP*LANES-1];
    reg cg_carry[0:ROW_GROUP*LANES-1];''')
    marker = '            always @(posedge register_clk or negedge rst_n) begin'
    product = 'cg_product[lane_id]' if 'cg_booth_lanes' in text else "36'(mac_a*$signed(pm_rdata[lane_id*16+:16]))"
    block = '''            wire [35:0] cg_bias=36'($signed(bias_pair[(lane_id%%2)*64+:64]));
            wire [35:0] cg_p=%s;
            wire [18:0] cg_sum={1'b0,cg_low[group_id*LANES+lane_id]}+{1'b0,cg_p[17:0]};
            wire [17:0] cg_effective_high=cg_high[group_id*LANES+lane_id]+18'(cg_carry[group_id*LANES+lane_id]);
            assign accumulator[group_id*LANES+lane_id]={cg_effective_high,cg_low[group_id*LANES+lane_id]};
''' % product
    text = replace(text, marker, block + marker)
    reset = 'cg_low[group_id*LANES+lane_id]<=0;cg_high[group_id*LANES+lane_id]<=0;cg_carry[group_id*LANES+lane_id]<=0;'
    text = replace(text, 'accumulator[group_id*LANES+lane_id]<=0;', reset)
    text = replace(text, "accumulator[group_id*LANES+lane_id]<=36'($signed(bias_pair[(lane_id%2)*64+:64]));", '''cg_low[group_id*LANES+lane_id]<=cg_bias[17:0];
                        cg_high[group_id*LANES+lane_id]<=cg_bias[35:18];cg_carry[group_id*LANES+lane_id]<=0;''')
    text = replace(text, 'if(mac_update) accumulator[group_id*LANES+lane_id]<=accumulator[group_id*LANES+lane_id]+' + product + ';', '''if(mac_update)begin
                        cg_low[group_id*LANES+lane_id]<=cg_sum[17:0];cg_carry[group_id*LANES+lane_id]<=cg_sum[18];
                        cg_high[group_id*LANES+lane_id]<=cg_high[group_id*LANES+lane_id]+cg_p[35:18]+18'(cg_carry[group_id*LANES+lane_id]);
                    end''')
    return text


def gray_address(text):
    function = '''    function automatic [12:0] cg_weight_address(input [12:0] original);
        reg [5:0] gray_inner;
        begin gray_inner=original[9:4]^(original[9:4]>>1);
            cg_weight_address={3'd0,original[3:0],gray_inner};end
    endfunction
'''
    text = replace(text, '    always @* begin', function + '    always @* begin')
    text = replace(text, "pm_addr[bank_index*13+:13]=13'(address/LANES);", "pm_addr[bank_index*13+:13]=cg_weight_address(13'(address/LANES));")
    text = replace(text, "pm_addr[b*13+:13]=13'(int'(weight_address)/LANES);", "pm_addr[b*13+:13]=cg_weight_address(13'(int'(weight_address)/LANES));")
    return text


def cut_through(text):
    emission = '    wire emission=(state==EMIT)||(state==STASH_OUT);\n'
    text = replace(text, emission, '')
    text = replace(text, '    wire pair_pop=', emission + '    wire pair_pop=')
    text = replace(text, 'wire pair_pop=FAST_PAIR&&out_pair_ready&&(fifo_count>=2);',
                   'wire pair_pop=FAST_PAIR&&out_pair_ready&&((fifo_count>=2)||((fifo_count==1)&&emission));')
    text = replace(text, 'assign out_pair_valid=fifo_count>=2;',
                   'assign out_pair_valid=(fifo_count>=2)||((fifo_count==1)&&emission);')
    text = replace(text, 'assign out_high=$signed(fifo[next_read]);',
                   'assign out_high=(fifo_count==1&&emission)?$signed(fifo_word):$signed(fifo[next_read]);')
    tail = '            endcase\n        end\n    end\nendmodule'
    text = replace(text, tail, '''            endcase
            if(pop_count!=0&&item+int'(pop_count)==25344)begin
                done<=1;input_count<=0;parameter_count<=0;shift_count<=0;clear_index<=0;state<=CLEAR;
            end
        end
    end
endmodule''')
    return text


def expand_fifo(text):
    substitutions=[('fifo[0:15]','fifo[0:63]'),('reg [3:0] fifo_write,fifo_read;','reg [5:0] fifo_write,fifo_read;'),
        ('reg [4:0] fifo_count;','reg [6:0] fifo_count;'),('fifo_count<16','fifo_count<64'),
        ('wire [3:0] next_read=','wire [5:0] next_read='),("fifo_read+4'(pop_count)","fifo_read+6'(pop_count)"),
        ("fifo_count+5'(fifo_push)-5'(pop_count)","fifo_count+7'(fifo_push)-7'(pop_count)"),
        ('fifo_bank<8;','fifo_bank<32;'),("fifo_write[3:1]==3'(fifo_bank)","fifo_write[5:1]==5'(fifo_bank)")]
    for before,after in substitutions:text=text.replace(before,after)
    return text


def prepare(name):
    manifest = load(name)
    out = ROOT / 'build/optimization/rtl_sources' / name
    copy_tree(ROOT / manifest['parent']['source_snapshot'], out)
    path = out / 'encoder/kwt_encoder.sv'
    text = path.read_text()
    flags = set(manifest['hardware'])
    if flags & {'P', 'E'}:
        text = schedule(text, 'P' in flags, 'E' in flags)
    if 'M' in flags:
        text = booth(text)
    if 'D18' in flags:
        text = split_accumulator(text)
    if 'GADDR' in flags:
        text = gray_address(text)
    if 'U' in flags:
        text = cut_through(text)
    if 'FIFO64' in flags:
        text = expand_fifo(text)
    if flags:
        with path.open('w', newline='\n') as stream:
            stream.write(text)
    if manifest['effective_changes'].get('bias32'):
        prove_bias32(REPORT / (name + '-bias32-proof.json'))
    return out


def variants():
    return {name: ['PIPE', 'OUTPUT'] for name in candidates()}


if __name__ == '__main__':
    import sys
    for name in sys.argv[1:]:
        print(prepare(name))
