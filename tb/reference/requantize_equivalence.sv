module requantize_equivalence (
    input wire signed [63:0] value,
    input wire signed [7:0] shift,
    output wire equivalent
);
    wire [15:0] original_result, optimized_result;
    kwt_requantize_original original(.value(value),.shift(shift),.result(original_result));
    kwt_requantize optimized(.value(value),.shift(shift),.result(optimized_result));
    assign equivalent = original_result == optimized_result;
endmodule
