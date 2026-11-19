module kwt_ffn_quantizer_check(
    input wire signed [63:0] value,
    input wire signed [7:0] shift,
    output wire signed [15:0] generic_result,special_result
);
    kwt_requantize generic_quantizer(.value(value),.shift(shift),.result(generic_result));
    kwt_ffn_requantize specialized_quantizer(.value(value),.shift(shift),.result(special_result));
endmodule
