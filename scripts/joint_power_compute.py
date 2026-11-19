"""Remove the empty SEED control cycle and gate actual register updates."""
from area_power_compute import _replace


def skip_seed(text):
    text = _replace(text, 'wire ap_er_seed_wait=state==AP_ER_SEED;',
                    'wire ap_er_seed_wait=(state==MAC_INIT)&&ap_er_next_seed_ready;')
    text = _replace(text, 'MAC_INIT:begin chunk<=0;state<=ap_er_next_seed_ready?AP_ER_SEED:BIAS_REQ;end',
                    'MAC_INIT:begin chunk<=0;if(ap_er_next_seed_ready)begin inner<=0;state<=A_REQ;end else state<=BIAS_REQ;end')
    return text


def pair_gates(text):
    start = text.index('    wire datapath_clk;')
    end = text.index('    generate for(genvar fifo_bank=', start)
    block = '''    reg [15:0] jp_shift_return;
    always_latch if(!clk)jp_shift_return=shift_rdata;
    generate for(genvar jp_pair=0;jp_pair<8;jp_pair=jp_pair+1)begin: jp_register_pairs
        wire seed_update=(bias_capture&&chunk==3'(jp_pair))||
            (ap_er_reseed&&lane[3:1]==3'(jp_pair));
        wire mac_update=(state==B_MAC)||(state==ROW1_MAC);
        wire accumulator_clk,shift_register_clk;
        if(CLOCK_GATING)begin: gated
            kwt_ffn_clock_gate accumulator_gate(.clk(clk),.enable(mac_update||seed_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(accumulator_clk));
            kwt_ffn_clock_gate shift_gate(.clk(clk),.enable(seed_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shift_register_clk));
        end else begin
            assign accumulator_clk=clk;
            assign shift_register_clk=clk;
        end
        for(genvar jp_half=0;jp_half<2;jp_half=jp_half+1)begin: words
            localparam integer jp_lane=jp_pair*2+jp_half;
            always @(posedge accumulator_clk or negedge rst_n)begin
                if(!rst_n)accumulator[jp_lane]<=0;
                else if(seed_update)accumulator[jp_lane]<=36'($signed(bias_pair[jp_half*64+:64]));
                else if(mac_update)accumulator[jp_lane]<=accumulator[jp_lane]+36'(mac_a*$signed(pm_rdata[jp_lane*16+:16]));
            end
            always @(posedge shift_register_clk or negedge rst_n)begin
                if(!rst_n)shifts[jp_lane]<=0;
                else if(seed_update)shifts[jp_lane]<=$signed(jp_shift_return[jp_half*8+:8]);
            end
        end
    end endgenerate
'''
    return text[:start] + block + text[end:]
