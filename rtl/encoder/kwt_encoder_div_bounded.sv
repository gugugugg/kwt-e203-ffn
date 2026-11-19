// Exact RNE division for the Softmax and 64-feature LayerNorm quotient bounds.
module kwt_encoder_div_bounded(
    input wire clk,rst_n,start,
    input wire signed [63:0] numerator,
    input wire [63:0] denominator,
    input wire [4:0] last_bit,
    output reg busy,done,error,
    output reg signed [63:0] result
);
    reg negative;
    reg [63:0] divisor,trial,remainder,quotient;
    reg [4:0] bit_index;
    wire take=remainder>=trial;
    wire [63:0] next_rem=take?remainder-trial:remainder;
    wire [63:0] next_q=quotient|(take?(64'd1<<bit_index):64'd0);
    wire [64:0] twice_rem={next_rem,1'b0};
    wire increment=(twice_rem>{1'b0,divisor})||
                   ((twice_rem=={1'b0,divisor})&&next_q[0]);
    wire [63:0] rounded=next_q+64'(increment);
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            busy<=0;done<=0;error<=0;result<=0;negative<=0;
            divisor<=1;trial<=0;remainder<=0;quotient<=0;bit_index<=0;
        end else begin
            done<=0;
            if(start&&!busy) begin
                error<=denominator==0;
                if(denominator==0) begin result<=0;done<=1;end
                else begin
                    busy<=1;negative<=numerator[63];divisor<=denominator;
                    trial<=denominator<<last_bit;bit_index<=last_bit;quotient<=0;
                    remainder<=numerator[63]?$unsigned(-numerator):$unsigned(numerator);
                end
            end else if(busy) begin
                remainder<=next_rem;quotient<=next_q;trial<=trial>>1;
                if(bit_index==0) begin
                    result<=negative?-$signed(rounded):$signed(rounded);
                    busy<=0;done<=1;
                end else bit_index<=bit_index-1'b1;
            end
        end
    end
endmodule
