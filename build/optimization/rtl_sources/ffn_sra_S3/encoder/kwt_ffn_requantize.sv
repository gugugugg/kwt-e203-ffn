module kwt_ffn_requantize(
    input wire signed [63:0] value,
    input wire [2:0] shift,
    output reg signed [15:0] result
);
    reg signed [63:0] quotient;
    reg guard_bit,sticky;
    always @* begin
        quotient=0;guard_bit=0;sticky=0;
        case(shift)
            3'd1:begin quotient=value>>>13;guard_bit=value[12];sticky=|value[11:0];end
            3'd2:begin quotient=value>>>14;guard_bit=value[13];sticky=|value[12:0];end
            3'd3:begin quotient=value>>>15;guard_bit=value[14];sticky=|value[13:0];end
            3'd4:begin quotient=value>>>16;guard_bit=value[15];sticky=|value[14:0];end
            3'd5:begin quotient=value>>>17;guard_bit=value[16];sticky=|value[15:0];end
            3'd6:begin quotient=value>>>18;guard_bit=value[17];sticky=|value[16:0];end
            default:begin end
        endcase
        if(quotient>=32767) result=16'sh7fff;
        else if(quotient< -32768) result=16'sh8000;
        else result=quotient[15:0]+{15'b0,(guard_bit&&(sticky||quotient[0]))};
    end
endmodule
