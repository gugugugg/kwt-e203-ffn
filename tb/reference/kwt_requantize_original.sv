// fixed16-v1: signed RNE (ties-even), then int16 saturation. No wraparound.
module kwt_requantize_original (
    input  wire signed [63:0] value,
    input  wire signed [7:0]  shift,
    output reg  signed [15:0] result
);
    reg signed [127:0] wide_value, quotient, remainder, halfway, rounded;
    always @* begin
        wide_value = {{64{value[63]}}, value};
        quotient = 128'sd0;
        remainder = 128'sd0;
        halfway = 128'sd0;
        rounded = wide_value;
        if ((shift > 0) && (shift <= 62)) begin
            quotient = wide_value >>> shift;
            remainder = wide_value - (quotient <<< shift);
            halfway = 128'sd1 <<< (shift - 8'sd1);
            rounded = quotient;
            if ((remainder > halfway) || ((remainder == halfway) && quotient[0]))
                rounded = quotient + 128'sd1;
        end else if ((shift < 0) && (shift >= -30)) begin
            rounded = wide_value <<< (-shift);
        end else if ((shift > 62) || (shift < -30)) begin
            rounded = 128'sd0; // Outside model domain; caller must flag an error.
        end
        if (rounded > 128'sd32767) result = 16'sh7fff;
        else if (rounded < -128'sd32768) result = 16'sh8000;
        else result = rounded[15:0];
    end
endmodule

