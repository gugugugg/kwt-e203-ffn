module pair_slice #(
    parameter bit PAIRED = 0
)(
    input wire clk, rst_n, valid, side, tail,
    input wire [5:0] k,
    input wire [63:0] activation,
    input wire [31:0] weight,
    input wire [71:0] bias,
    input wire [143:0] row_adjustment,
    input wire [15:0] shifts,
    output reg [127:0] result,
    output reg result_valid
);
    wire [287:0] quant_source;
    wire [127:0] rounded;
    wire retire, retire_side, retire_tail;
    if (!PAIRED) begin: reference
        reg seen, save_side, save_tail;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin seen<=0;save_side<=0;save_tail<=0;end
            else begin seen<=valid&&k==63;save_side<=side;save_tail<=tail;end
        end
        assign retire=seen;
        assign retire_side=save_side;
        assign retire_tail=save_tail;
        for (genvar col=0;col<2;col=col+1) begin: columns
            wire [3:0] ck;
            kwt_ffn_clock_gate ga(clk,valid&&!side,1'b0,ck[0]);
            kwt_ffn_clock_gate gb(clk,valid&&side,1'b0,ck[1]);
            kwt_ffn_clock_gate gfa(clk,valid&&!side&&!tail,1'b0,ck[2]);
            kwt_ffn_clock_gate gfb(clk,valid&&side&&!tail,1'b0,ck[3]);
            for (genvar row=0;row<4;row=row+1) begin: lanes
                localparam integer GATE=(row==3)?2:0;
                reg signed [35:0] a,b;
                wire signed [31:0] product=$signed(activation[row*16+:16])*$signed(weight[col*16+:16]);
                wire signed [35:0] prior=k==0?$signed(bias[col*36+:36]):side?b:a;
                wire signed [35:0] value=prior+{{4{product[31]}},product};
                always @(posedge ck[GATE]) a<=value;
                always @(posedge ck[GATE+1]) b<=value;
                assign quant_source[(4*col+row)*36+:36]=retire_side?b:a;
            end
        end
    end else begin: paired
        reg [2:0] phase;
        reg [63:0] a_even,b_even,a_odd,b_odd;
        reg [31:0] next_weight_even,live_weight_even,live_weight_odd;
        reg first_pair, is_tail;
        wire immediate=valid&&k[0]&&!side;
        wire prepare=immediate||phase!=0;
        wire front_side=!immediate&&(phase==2||phase==3);
        wire front_upper=!immediate&&(phase==1||phase==3||phase==4);
        wire front_first=immediate?k==1:first_pair;
        wire front_tail=immediate?tail:is_tail;
        wire [63:0] even_vec=front_side?b_even:a_even;
        wire [63:0] odd_vec=immediate?activation:front_side?b_odd:a_odd;
        wire [31:0] even_w=immediate?next_weight_even:live_weight_even;
        wire [31:0] odd_w=immediate?weight:live_weight_odd;
        wire [1:0] even_clk, odd_clk;
        wire save_w_clk, active_w_clk;
        kwt_ffn_clock_gate ega(clk,valid&&!k[0]&&!side,1'b0,even_clk[0]);
        kwt_ffn_clock_gate egb(clk,valid&&!k[0]&&side,1'b0,even_clk[1]);
        kwt_ffn_clock_gate oga(clk,immediate,1'b0,odd_clk[0]);
        kwt_ffn_clock_gate ogb(clk,valid&&k[0]&&side,1'b0,odd_clk[1]);
        kwt_ffn_clock_gate wge(clk,valid&&!k[0]&&!side,1'b0,save_w_clk);
        kwt_ffn_clock_gate wgl(clk,immediate,1'b0,active_w_clk);
        always @(posedge even_clk[0]) a_even<=activation;
        always @(posedge even_clk[1]) b_even<=activation;
        always @(posedge odd_clk[0]) a_odd<=activation;
        always @(posedge odd_clk[1]) b_odd<=activation;
        always @(posedge save_w_clk) next_weight_even<=weight;
        always @(posedge active_w_clk) begin live_weight_even<=next_weight_even;live_weight_odd<=weight;end
        reg [3:0] finish, sides, tails;
        reg exec, exec_side, exec_upper, exec_first, exec_tail;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                phase<=0;first_pair<=0;is_tail<=0;finish<=0;sides<=0;tails<=0;
                exec<=0;exec_side<=0;exec_upper<=0;exec_first<=0;exec_tail<=0;
            end else begin
                if(immediate) begin phase<=tail?3'd4:3'd1;first_pair<=k==1;is_tail<=tail;end
                else if(phase!=0) phase<=phase>=3?3'd0:phase+3'd1;
                finish<={finish[2:0],valid&&k==63};
                sides<={sides[2:0],side};
                tails<={tails[2:0],tail};
                exec<=prepare;exec_side<=front_side;exec_upper<=front_upper;
                exec_first<=front_first;exec_tail<=front_tail;
            end
        end
        assign retire=finish[3];
        assign retire_side=sides[3];
        assign retire_tail=tails[3];
        for(genvar col=0;col<2;col=col+1) begin: columns
            wire [1:0] pre_clk;
            wire [71:0] products;
            for(genvar lane=0;lane<2;lane=lane+1) begin: main
                localparam integer LANE=lane;
                wire [5:0] offset={front_upper,1'b0,4'b0}+6'(16*LANE);
                wire signed [15:0] ae=even_vec[offset+:16];
                wire signed [15:0] ao=odd_vec[offset+:16];
                wire signed [15:0] we=even_w[col*16+:16], wo=odd_w[col*16+:16];
                reg signed [16:0] left,right;
                kwt_ffn_clock_gate pre(clk,prepare&&!(front_tail&&front_upper&&LANE==1),1'b0,pre_clk[LANE]);
                always @(posedge pre_clk[LANE]) begin
                    left<={ae[15],ae}+{wo[15],wo};
                    right<={ao[15],ao}+{we[15],we};
                end
                wire signed [33:0] product=left*right;
                assign products[LANE*36+:36]={{2{product[33]}},product};
            end
            for(genvar row=0;row<4;row=row+1) begin: lanes
                reg signed [35:0] a,b;
                wire hit=exec&&(exec_upper==(row>=2))&&!(exec_tail&&row==3);
                wire cka,ckb;
                kwt_ffn_clock_gate ga(clk,hit&&!exec_side,1'b0,cka);
                kwt_ffn_clock_gate gb(clk,hit&&exec_side,1'b0,ckb);
                wire signed [35:0] prior=exec_first?36'sd0:exec_side?b:a;
                wire signed [35:0] value=prior+$signed(products[(row%2)*36+:36]);
                always @(posedge cka) a<=value;
                always @(posedge ckb) b<=value;
                wire consume=retire&&!(retire_tail&&row==3);
                wire [35:0] old_acc=consume?(retire_side?b:a):36'd0;
                wire [35:0] column_bias=consume?bias[col*36+:36]:36'd0;
                wire [35:0] row_bias=consume?row_adjustment[row*36+:36]:36'd0;
                wire [35:0] sum_bits=old_acc^column_bias^row_bias;
                wire [35:0] carry_bits=((old_acc&column_bias)|(old_acc&row_bias)|(column_bias&row_bias))<<1;
                assign quant_source[(4*col+row)*36+:36]=sum_bits+carry_bits;
            end
        end
    end
    for (genvar lane=0;lane<8;lane=lane+1) begin: quant
        wire signed [35:0] value=retire&&(!retire_tail||lane%4!=3)?
                               quant_source[lane*36+:36]:36'sd0;
        wire signed [7:0] shift=retire?shifts[(lane/4)*8+:8]:8'sd0;
        kwt_ffn_requantize q(.value({{28{value[35]}},value}),.shift(shift),
                             .result(rounded[lane*16+:16]));
    end
    always @(posedge clk or negedge rst_n)
        if(!rst_n) result_valid<=0;
        else result_valid<=retire;
    always @(posedge clk) if(retire) result<=rounded;
endmodule

