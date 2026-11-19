`timescale 1ns/1ps
module encoder_math_tb;
    reg clk=0,rst_n=0,start_div=0,start_sqrt=0;
    always #5 clk=~clk;
    reg signed [63:0] numerator;
    reg [63:0] denominator;
    reg [127:0] radicand;
    wire div_busy,div_done,div_error,sqrt_busy,sqrt_done;
    wire signed [63:0] result_div;
    wire [63:0] result_sqrt;
    kwt_encoder_div64 d(.clk(clk),.rst_n(rst_n),.start(start_div),.numerator(numerator),.denominator(denominator),.busy(div_busy),.done(div_done),.error(div_error),.result(result_div));
    kwt_encoder_sqrt128 s(.clk(clk),.rst_n(rst_n),.start(start_sqrt),.radicand(radicand),.busy(sqrt_busy),.done(sqrt_done),.result(result_sqrt));
    integer fd,n,count=0;
    reg [63:0] expected;
    initial begin
        repeat(3) @(negedge clk); rst_n=1;
        fd=$fopen("build/encoder/vectors/div_vectors.txt","r");
        while(!$feof(fd)) begin
            n=$fscanf(fd,"%h %h %h\n",numerator,denominator,expected);
            if(n==3) begin
                start_div=1; @(negedge clk); start_div=0;
                wait(div_done); @(negedge clk);
                if(div_error || result_div!==expected) $fatal(1,"DIV mismatch n=%h d=%h got=%h expected=%h",numerator,denominator,result_div,expected);
                count=count+1;
            end
        end
        $fclose(fd); $display("DIV_PASS count=%0d",count); count=0;
        fd=$fopen("build/encoder/vectors/sqrt_vectors.txt","r");
        while(!$feof(fd)) begin
            n=$fscanf(fd,"%h %h\n",radicand,expected);
            if(n==2) begin
                start_sqrt=1; @(negedge clk); start_sqrt=0;
                wait(sqrt_done); @(negedge clk);
                if(result_sqrt!==expected) $fatal(1,"SQRT mismatch rad=%h got=%h expected=%h",radicand,result_sqrt,expected);
                count=count+1;
            end
        end
        $fclose(fd); $display("SQRT_PASS count=%0d",count);
        // Zero denominator must report failure, and reset must abort an operation.
        numerator=3; denominator=0; start_div=1; @(negedge clk); start_div=0;
        if(!div_done || !div_error) $fatal(1,"Missing division-by-zero error");
        denominator=7; start_div=1; start_sqrt=1; repeat(3) @(negedge clk);
        rst_n=0; start_div=0; start_sqrt=0; @(negedge clk);
        if(div_busy || sqrt_busy || div_done || sqrt_done) $fatal(1,"Reset did not abort math");
        $display("PASS encoder integer primitives"); $finish;
    end
    initial begin #1000000; $fatal(1,"Math timeout"); end
endmodule
