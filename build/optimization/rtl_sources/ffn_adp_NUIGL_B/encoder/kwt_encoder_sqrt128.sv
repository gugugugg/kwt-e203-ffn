// Exact fixed16-v1 integer primitive.
module kwt_encoder_sqrt128(
    input wire clk,rst_n,start,
    input wire [127:0] radicand,
    output reg busy,done,
    output reg [63:0] result
);
    reg [127:0] operand;
    reg [129:0] remainder;
    reg [63:0] root;
    reg [6:0] count;
    wire [129:0] shifted=(remainder<<2)|{128'b0,operand[127:126]};
    wire [129:0] trial=({66'b0,root}<<2)|130'd1;
    wire take=shifted>=trial;
    wire [63:0] next_root={root[62:0],take};
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin busy<=0; done<=0; result<=0; operand<=0; remainder<=0; root<=0; count<=0; end
        else begin
            done<=0;
            if(start&&!busy) begin busy<=1; operand<=radicand; remainder<=0; root<=0; count<=0; end
            else if(busy) begin
                operand<=operand<<2; remainder<=take?shifted-trial:shifted; root<=next_root;
                if(count==63) begin busy<=0; done<=1; result<=next_root; end
                else count<=count+1'b1;
            end
        end
    end
endmodule
