// Signed nearest-even rounding and int16 saturation; combinational latency.
module kwt_requantize (
    input  wire signed [63:0] value,
    input  wire signed [7:0]  shift,
    output reg  signed [15:0] result
);
    wire [63:0] lower_nonzero;
    assign lower_nonzero[0] = 1'b0;
    generate
        for (genvar bit_index=1; bit_index<64; bit_index=bit_index+1) begin: sticky_bits
            assign lower_nonzero[bit_index] = |value[bit_index-1:0];
        end
    endgenerate
    wire signed [64:0] shifted = $signed({value,1'b0}) >>> shift[5:0];
    wire signed [63:0] quotient = shifted[64:1];
    wire [5:0] guard_index = shift[5:0] - 6'd1;
    wire round_up = shifted[0] && (lower_nonzero[guard_index] || quotient[0]);
    wire [4:0] left_count = -shift[4:0];
    wire signed [15:0] left_max = 16'sh7fff >>> left_count[3:0];
    wire signed [15:0] left_min = $signed(16'sh8000) >>> left_count[3:0];
    always @* begin
        result = 16'sd0;
        if ((shift > 0) && (shift <= 62)) begin
            if (quotient >= 64'sd32767) result = 16'sh7fff;
            else if (quotient < -64'sd32768) result = 16'sh8000;
            else result = quotient[15:0] + {15'b0,round_up};
        end else if ((shift < 0) && (shift >= -30)) begin
            if (left_count >= 16) begin
                if (value > 0) result = 16'sh7fff;
                else if (value < 0) result = 16'sh8000;
            end else begin
                if (value > $signed({{48{left_max[15]}},left_max})) result = 16'sh7fff;
                else if (value < $signed({{48{left_min[15]}},left_min})) result = 16'sh8000;
                else result = value[15:0] << left_count;
            end
        end else if (shift == 0) begin
            if (value > 64'sd32767) result = 16'sh7fff;
            else if (value < -64'sd32768) result = 16'sh8000;
            else result = value[15:0];
        end
    end
endmodule
