module parity_equivalence(input clk,reset,valid,data,output equivalent);
    reg [30:0] tags, seen, reference;
    reg phase;
    wire [15:0] match, phase_match;
    wire [14:0] source_match;
    always @(posedge clk) begin
        if (reset) begin
            tags<=0;
            seen<=0;
            phase<=0;
        end else begin
            tags<={tags[29:0],valid};
            phase<=!phase;
            seen<=seen|{tags[29:0],valid};
            if (valid) reference[0]<=data;
            for(integer stage=1;stage<31;stage++)
                if(tags[stage-1]) reference[stage]<=reference[stage-1];
        end
    end
    wire [15:0] bank0,bank1;
    for(genvar tap=0;tap<16;tap++) begin: slice
        reg a,b,last;
        wire advance=tap==0?valid:tags[2*tap-1];
        wire in0,in1;
        if(tap==0) begin
            assign in0=data;
            assign in1=data;
        end else begin
            assign in0=bank0[tap-1];
            assign in1=bank1[tap-1];
            assign source_match[tap-1]=!tags[2*tap-1]||
                ((phase?in1:in0)==reference[2*tap-1]);
        end
        always @(posedge clk) if(!reset&&advance) begin
            if(phase) b<=in1;
            else a<=in0;
            last<=phase;
        end
        assign bank0[tap]=a;
        assign bank1[tap]=b;
        assign match[tap]=!seen[2*tap]||((last?b:a)==reference[2*tap]);
        assign phase_match[tap]=!tags[2*tap]||(seen[2*tap]&&last==!phase);
    end
    assign equivalent=reset||((&match)&&(&phase_match)&&(&source_match));
endmodule
