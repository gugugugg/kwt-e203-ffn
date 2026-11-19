// Exact fixed16-v1 integer primitive.
module kwt_encoder_div64(
    input wire clk,rst_n,start,
    input wire signed [63:0] numerator,
    input wire [63:0] denominator,
    output reg busy,done,error,
    output reg signed [63:0] result
);
    reg negative;
    reg [63:0] dividend,divisor;
    reg [62:0] quotient;
    reg [63:0] remainder;
    reg [6:0] count;
    wire [64:0] shifted={remainder,dividend[63]};
    wire take=shifted>={1'b0,divisor};
    wire [64:0] next_rem=take?shifted-{1'b0,divisor}:shifted;
    wire [63:0] next_q={quotient,take};
    wire increment=({next_rem,1'b0}>{2'b0,divisor}) ||
                   (({next_rem,1'b0}=={2'b0,divisor})&&next_q[0]);
    wire [63:0] rounded=next_q+64'(increment);
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin busy<=0; done<=0; error<=0; result<=0;
            negative<=0; dividend<=0; divisor<=1; quotient<=0; remainder<=0; count<=0;
        end else begin
            done<=0;
            if(start&&!busy) begin
                error<=denominator==0;
                if(denominator==0) begin result<=0; done<=1; end
                else begin
                    busy<=1; count<=0; quotient<=0; remainder<=0;
                    negative<=numerator[63]; dividend<=numerator[63]?$unsigned(-numerator):$unsigned(numerator);
                    divisor<=denominator;
                end
            end else if(busy) begin
                dividend<=dividend<<1; quotient<=next_q[62:0]; remainder<=next_rem[63:0];
                if(count==63) begin
                    result<=negative?-$signed(rounded):$signed(rounded); busy<=0; done<=1;
                end else count<=count+1'b1;
            end
        end
    end
endmodule
