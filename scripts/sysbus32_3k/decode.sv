module kwt_lossless_decode #(parameter INPUT_PACKET = 0) (
    input wire clk, rst_n, restart,
    input wire input_valid,
    output wire input_ready,
    input wire [31:0] input_word,
    output wire output_valid,
    input wire output_ready,
    output wire [31:0] output_word,
    output wire packet_done
);
    reg active;
    reg [3:0] k, shift_width;
    reg [5:0] bias_width;
    reg [7:0] shift_base;
    reg [12:0] index;
    reg [63:0] bits;
    reg [6:0] fill;
    reg [31:0] assembled;
    reg [1:0] count;
    reg [31:0] fifo [0:1];
    reg head, tail;
    reg [5:0] inner;
    reg [1:0] tail_lane;
    reg [15:0] prev, saved1, saved5;
    reg [15:0] row7 [0:63];

    wire end_symbols = index == (INPUT_PACKET ? 13'd6336 : 13'd1056);
    assign packet_done = active && end_symbols && count == 0;
    assign input_ready = !active || (!end_symbols && fill <= 32);
    wire refill = input_valid && input_ready;
    wire pop = output_valid && output_ready;
    assign output_valid = count != 0;
    assign output_word = fifo[head];
    wire raw = INPUT_PACKET && index < 512 && index[2:0] == 0;
    wire bias = !INPUT_PACKET && index < 16;
    wire shift_value = !INPUT_PACKET && index >= 16 && index < 32;
    wire [2:0] input_lane = index[2:0];
    wire [15:0] prediction = index >= 6144 ? (tail_lane == 0 ? row7[inner] : prev) :
                             input_lane == 0 ? row7[inner] : input_lane == 4 ? saved1 :
                             input_lane == 6 ? saved5 : prev;
    reg [4:0] quotient;
    reg [6:0] size;
    reg [5:0] width;
    reg [31:0] value;
    reg [15:0] zigzag;
    reg [31:0] word;
    reg last_symbol;
    integer lane;
    always @* begin
        quotient = 0;
        for (lane = 0; lane < (INPUT_PACKET ? 15 : 8); lane = lane+1)
            if (bits[lane] && quotient == lane) quotient = quotient + 5'd1;
        size = 0;
        width = 0;
        value = 0;
        zigzag = 0;
        word = 0;
        last_symbol = 0;
        if (bias) begin
            width = bias_width;
            size = {1'b0, width};
            if (index == 15 && width[0]) size = size + 7'd16;
            value = $signed(bits[31:0] << (6'd32-width)) >>> (6'd32-width);
            word = value;
            last_symbol = 1;
        end else if (shift_value) begin
            width = {2'b0, shift_width};
            size = {1'b0, width};
            if (index == 31 && width[0]) size = size + 7'd16;
            value = {24'b0,shift_base} + (bits[7:0] & (8'hff >> (6'd8-width)));
            word = assembled | ({24'b0,value[7:0]} << {index[1:0],3'b0});
            last_symbol = index[1:0] == 3;
        end else begin
            if (raw) begin
                size = 16;
                value = {16'b0,bits[15:0]};
            end else begin
                if (INPUT_PACKET && quotient == 15) begin
                    size = 31;
                    zigzag = bits[30:15];
                end else begin
                    size = {2'b0,quotient} + {3'b0,k} + 7'd1;
                    zigzag = (16'(quotient) << k) |
                             (16'(bits >> (quotient + 5'd1)) & (16'hffff >> (5'd16-{1'b0,k})));
                end
                value[15:0] = (zigzag >> 1) ^ {16{zigzag[0]}};
                if (INPUT_PACKET) value[15:0] = value[15:0] + prediction;
            end
            word = index[0] ? {value[15:0], assembled[15:0]} : {16'b0,value[15:0]};
            last_symbol = index[0];
        end
    end
    wire decode = active && !end_symbols && fill >= size && count < 2;
    wire push = decode && last_symbol;
    wire [6:0] kept = decode ? fill-size : fill;
    wire [63:0] remaining = decode ? bits >> size : bits;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active<=0; index<=0; fill<=0; bits<=0; count<=0; head<=0; tail<=0;
            assembled<=0; inner<=0; tail_lane<=0;
        end else if (restart) begin
            active<=0; index<=0; fill<=0; bits<=0; count<=0; head<=0; tail<=0;
            assembled<=0; inner<=0; tail_lane<=0;
        end else if (!active && refill) begin
            active<=1;
            k<=INPUT_PACKET ? input_word[3:0] : input_word[30:27];
            bias_width<={1'b0,input_word[14:10]}+6'd1;
            shift_base<=input_word[22:15];
            shift_width<=input_word[26:23];
        end else begin
            if (refill || decode) begin
                bits<=remaining | (refill ? ({32'b0,input_word} << kept) : 64'b0);
                fill<=kept+(refill ? 7'd32 : 7'd0);
            end
            if (decode) begin
                index<=index+13'd1;
                assembled<=last_symbol ? 32'b0 : word;
                if (INPUT_PACKET) begin
                    prev<=value[15:0];
                    if (input_lane==1) saved1<=value[15:0];
                    if (input_lane==3) saved5<=value[15:0];
                    if (index<6144 && input_lane==7) row7[inner]<=value[15:0];
                    if ((index<6144 && input_lane==7) || (index>=6144 && tail_lane==2)) inner<=inner+6'd1;
                    if (index>=6144) tail_lane<=tail_lane==2 ? 2'd0 : tail_lane+2'd1;
                end
            end
            if (push) begin fifo[tail]<=word; tail<=!tail; end
            if (pop) head<=!head;
            case ({push,pop})
                2'b10: count<=count+2'd1;
                2'b01: count<=count-2'd1;
                default: ;
            endcase
        end
    end
endmodule
