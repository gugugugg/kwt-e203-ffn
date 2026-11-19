module kwt_shared_icb_sm40(
    input wire clk,rst_n,
    input wire cpu_cmd_valid,
    output wire cpu_cmd_ready,
    input wire [31:0] cpu_cmd_addr,
    input wire cpu_cmd_read,
    input wire [31:0] cpu_cmd_wdata,
    input wire [3:0] cpu_cmd_wmask,
    output wire cpu_rsp_valid,
    input wire cpu_rsp_ready,
    output wire [31:0] cpu_rsp_rdata,
    output wire cpu_rsp_err,
    input wire host_cmd_valid,
    output wire host_cmd_ready,
    input wire host_cmd_read,
    input wire [16:0] host_cmd_addr,
    input wire [31:0] host_cmd_wdata,
    input wire [3:0] host_cmd_wmask,
    output reg host_rsp_valid,
    input wire host_rsp_ready,
    output reg [31:0] host_rsp_rdata
,
    input wire ld_cmd_valid,
    output wire ld_cmd_ready,
    input wire [31:0] ld_cmd_addr,
    input wire ld_cmd_read,
    input wire [31:0] ld_cmd_wdata,
    input wire [3:0] ld_cmd_wmask,
    output wire ld_rsp_valid,
    input wire ld_rsp_ready,
    output wire [31:0] ld_rsp_rdata,
    output wire ld_rsp_err,
    input wire wb_valid,
    output wire wb_ready,
    input wire [16:0] wb_addr,
    input wire [31:0] wb_data,
    output wire wb_ack_valid,
    input wire wb_ack_ready
);
wire joined_cmd_valid;
wire joined_cmd_ready;
wire [31:0] joined_cmd_addr;
wire joined_cmd_read;
wire [31:0] joined_cmd_wdata;
wire [3:0] joined_cmd_wmask;
wire joined_rsp_valid;
reg stored_rsp_valid;
wire joined_rsp_ready;
wire [31:0] joined_rsp_rdata;
reg [31:0] stored_rsp_rdata;
wire joined_rsp_err;
reg stored_rsp_err;
wire joined_cmd_dma;
wire read_handoff_allowed,read_handoff_eligible;
    wire staged_dma_ready;
    reg [11:0] input_committed;
    reg [13:0] parameter_committed;
    reg stream_enabled;
    wire [16:0] ld_word=ld_cmd_addr[18:2];
    wire host_input=!host_cmd_read&&host_cmd_wmask==4'hf&&host_cmd_addr<17'd3168;
    wire host_input_next=host_input&&host_cmd_addr=={5'b0,input_committed};
    wire host_parameter_next=!host_cmd_read&&host_cmd_wmask==4'hf&&
        parameter_committed<14'd8512&&host_cmd_addr==17'd32768+17'(parameter_committed);
    wire ld_input=ld_word<17'd3168;
    wire ld_parameter=ld_word>=17'd32768&&ld_word<17'd41280;
    wire dma_load_eligible=(ld_input&&ld_word<{5'b0,input_committed})||
        (ld_parameter&&ld_word<17'd32768+17'(parameter_committed));

    function automatic [16:0] bank_word(input [16:0] addr);
        begin
            if(addr[16:13]==4'b0100 || addr[16:13]==4'b0000)
                bank_word={addr[16:13],addr[0],addr[11:1],addr[12]};
            else bank_word=addr;
        end
    endfunction
    wire [16:0] host_bank_word=bank_word(host_cmd_addr);
    wire [16:0] joined_bank_word=bank_word(joined_cmd_addr[18:2]);
    wire joined_address_valid=joined_cmd_addr[31:19]==13'h1400;
    wire joined_load_read=joined_cmd_dma&&joined_cmd_read&&joined_address_valid;
    wire joined_fire;
    wire host_stream=host_cmd_valid&&stream_enabled&&(host_input_next||host_parameter_next);
    wire host_dual_candidate=joined_fire&&joined_load_read&&host_stream;
    wire host_bank_conflict=host_dual_candidate&&host_bank_word[16:12]==joined_bank_word[16:12];
    wire host_dual=host_dual_candidate&&!host_bank_conflict;
    wire host_foreground=host_cmd_valid&&!host_stream;
    assign ld_cmd_ready=staged_dma_ready&&dma_load_eligible;
kwt_tp_shared_read_arbiter memory_arbiter(
.read_handoff_allowed(read_handoff_allowed),
.read_handoff_eligible(read_handoff_eligible),
.clk(clk),.rst_n(rst_n),
        .a_cmd_valid(cpu_cmd_valid),
        .a_cmd_ready(cpu_cmd_ready),
        .a_cmd_addr(cpu_cmd_addr),
        .a_cmd_read(cpu_cmd_read),
        .a_cmd_wdata(cpu_cmd_wdata),
        .a_cmd_wmask(cpu_cmd_wmask),
        .a_rsp_valid(cpu_rsp_valid),
        .a_rsp_ready(cpu_rsp_ready),
        .a_rsp_rdata(cpu_rsp_rdata),
        .a_rsp_err(cpu_rsp_err),
        .b_cmd_valid(ld_cmd_valid&&dma_load_eligible),
        .b_cmd_ready(staged_dma_ready),
        .b_cmd_addr(ld_cmd_addr),
        .b_cmd_read(ld_cmd_read),
        .b_cmd_wdata(ld_cmd_wdata),
        .b_cmd_wmask(ld_cmd_wmask),
        .b_rsp_valid(ld_rsp_valid),
        .b_rsp_ready(ld_rsp_ready),
        .b_rsp_rdata(ld_rsp_rdata),
        .b_rsp_err(ld_rsp_err),
        .s_cmd_valid(joined_cmd_valid),
        .s_cmd_ready(joined_cmd_ready),
        .s_cmd_addr(joined_cmd_addr),
        .s_cmd_read(joined_cmd_read),
        .s_cmd_dma(joined_cmd_dma),
        .s_cmd_wdata(joined_cmd_wdata),
        .s_cmd_wmask(joined_cmd_wmask),
        .s_rsp_valid(joined_rsp_valid),
        .s_rsp_ready(joined_rsp_ready),
        .s_rsp_rdata(joined_rsp_rdata),
        .s_rsp_err(joined_rsp_err));

    reg pending,read_pending,error_pending,to_host,pending_fast_access;
    wire [31:0] memory_rdata;
    wire next_fast_access=joined_load_read;
    wire early_response=pending&&pending_fast_access;
    assign joined_rsp_valid=early_response||stored_rsp_valid;
    assign joined_rsp_rdata=early_response?(read_pending?memory_rdata:32'b0):stored_rsp_rdata;
    assign joined_rsp_err=!early_response&&stored_rsp_err;
    wire idle=!pending&&!stored_rsp_valid&&!host_rsp_valid;
    assign host_cmd_ready=(idle&&(!host_stream||!joined_cmd_valid))||host_dual;
    assign read_handoff_allowed=(!pending||(early_response&&next_fast_access))&&
                               !host_foreground&&!host_rsp_valid;
    wire read_handoff=read_handoff_eligible&&joined_rsp_valid&&joined_rsp_ready;
    assign joined_cmd_ready=(idle||read_handoff)&&!host_foreground;
    assign joined_fire=joined_cmd_valid&&joined_cmd_ready;
    wire host_fire=host_cmd_valid&&host_cmd_ready;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin input_committed<=0; parameter_committed<=0; stream_enabled<=0;end
        else if(host_fire&&!host_cmd_read) begin
            if(host_input&&host_cmd_addr==0) begin
                input_committed<=1;parameter_committed<=0;stream_enabled<=0;
            end else if(host_input_next) input_committed<=input_committed+12'd1;
            else if(host_parameter_next) parameter_committed<=parameter_committed+14'd1;
            else if(host_cmd_addr==17'd131021&&host_cmd_wdata==1) stream_enabled<=1;
        end
    end
    wire host_primary=host_fire&&!host_dual;
    wire physical_accept=host_primary||(joined_fire&&joined_address_valid);
    wire live_we=host_primary?!host_cmd_read:!joined_cmd_read;
    wire [16:0] live_addr=host_primary?host_bank_word:joined_bank_word;
    wire [31:0] live_wdata=host_fire?host_cmd_wdata:joined_cmd_wdata;
    wire [3:0] live_wmask=host_fire?host_cmd_wmask:joined_cmd_wmask;
    wire physical_write=(physical_accept&&live_we)||host_dual;
    reg result_pending;
    wire wb_bank_valid=wb_addr>=17'h4000&&wb_addr<17'h7180;
    wire wb_primary_conflict=physical_accept&&live_addr[16:12]==wb_addr[16:12];
    wire wb_host_conflict=host_dual&&host_bank_word[16:12]==wb_addr[16:12];
    assign wb_ready=rst_n&&wb_bank_valid&&(!result_pending||wb_ack_ready)&&
        !wb_primary_conflict&&!wb_host_conflict;
    wire result_commit=wb_valid&&wb_ready;
    assign wb_ack_valid=result_pending;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) result_pending<=0;
        else if(result_commit) result_pending<=1;
        else if(wb_ack_ready) result_pending<=0;
    end
    reg [16:0] held_addr;
    reg held_we;
    reg [31:0] held_wdata;
    reg [3:0] held_wmask;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            held_addr<=0;held_we<=0;held_wdata<=0;held_wmask<=0;
        end else begin
            if(physical_accept) begin held_addr<=live_addr;held_we<=live_we;end
            if(physical_write) begin held_wdata<=live_wdata;held_wmask<=live_wmask;end
        end
    end
    kwt_bank_overlap_sram memory(
        .clk(clk),.en(physical_accept),
        .we(physical_accept?live_we:held_we),
        .addr(physical_accept?live_addr:held_addr),.stream_write(host_dual),.stream_addr(host_bank_word),
        .result_write(result_commit),.result_addr(wb_addr),.result_data(wb_data),
        .wdata(physical_write?live_wdata:held_wdata),
        .wmask(physical_write?live_wmask:held_wmask),.rdata(memory_rdata)
    );
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            pending<=0;read_pending<=0;error_pending<=0;pending_fast_access<=0;
            stored_rsp_valid<=0;stored_rsp_rdata<=0;stored_rsp_err<=0;
            host_rsp_valid<=0;host_rsp_rdata<=0;to_host<=0;
        end else begin
            if(stored_rsp_valid&&joined_rsp_ready) stored_rsp_valid<=0;
            if(host_rsp_valid&&host_rsp_ready) host_rsp_valid<=0;
            if(pending) begin
                pending<=0;
                if(to_host) begin
                    host_rsp_valid<=1;host_rsp_rdata<=memory_rdata;
                end else if(!early_response||!joined_rsp_ready) begin
                    stored_rsp_valid<=1;stored_rsp_err<=error_pending;
                    stored_rsp_rdata<=(read_pending&&!error_pending)?memory_rdata:32'b0;
                end
            end
            // A new accept may share the edge with retirement of the old SRAM Q.
            if(joined_fire) begin
                pending<=1;read_pending<=joined_cmd_read;
                error_pending<=!joined_address_valid;to_host<=0;
                pending_fast_access<=next_fast_access;
            end
            if(host_fire&&host_cmd_read) begin
                pending<=1;read_pending<=1;error_pending<=0;to_host<=1;
                pending_fast_access<=0;
            end
        end
    end
endmodule

module kwt_tp_shared_read_arbiter #(
    parameter integer AW=32
)(
    input wire clk,rst_n,read_handoff_allowed,
    output wire read_handoff_eligible,
    input wire a_cmd_valid,output wire a_cmd_ready,input wire [AW-1:0] a_cmd_addr,
    input wire a_cmd_read,input wire [31:0] a_cmd_wdata,input wire [3:0] a_cmd_wmask,
    output wire a_rsp_valid,input wire a_rsp_ready,output wire [31:0] a_rsp_rdata,output wire a_rsp_err,
    input wire b_cmd_valid,output wire b_cmd_ready,input wire [AW-1:0] b_cmd_addr,
    input wire b_cmd_read,input wire [31:0] b_cmd_wdata,input wire [3:0] b_cmd_wmask,
    output wire b_rsp_valid,input wire b_rsp_ready,output wire [31:0] b_rsp_rdata,output wire b_rsp_err,
    output wire s_cmd_valid,input wire s_cmd_ready,output wire [AW-1:0] s_cmd_addr,
    output wire s_cmd_read,output wire s_cmd_dma,output wire [31:0] s_cmd_wdata,output wire [3:0] s_cmd_wmask,
    input wire s_rsp_valid,output wire s_rsp_ready,input wire [31:0] s_rsp_rdata,input wire s_rsp_err
);
    reg active,owner,owner_read,prefer_b,held_valid,held_owner;
    wire grant=held_valid?held_owner:(b_cmd_valid&&(!a_cmd_valid||prefer_b));
    assign s_rsp_ready=active&&(owner?b_rsp_ready:a_rsp_ready);
    wire retire=active&&s_rsp_valid&&s_rsp_ready;
    assign read_handoff_eligible=read_handoff_allowed&&active&&owner&&
        grant&&b_cmd_valid&&(owner_read==b_cmd_read);
    wire available=!active||(read_handoff_eligible&&retire);
    assign s_cmd_valid=available&&(grant?b_cmd_valid:a_cmd_valid);
    assign s_cmd_addr=grant?b_cmd_addr:a_cmd_addr;
    assign s_cmd_read=grant?b_cmd_read:a_cmd_read;
    assign s_cmd_dma=grant;
    assign s_cmd_wdata=grant?b_cmd_wdata:a_cmd_wdata;
    assign s_cmd_wmask=grant?b_cmd_wmask:a_cmd_wmask;
    assign a_cmd_ready=available&&!grant&&s_cmd_ready;
    assign b_cmd_ready=available&&grant&&s_cmd_ready;
    wire fire=s_cmd_valid&&s_cmd_ready;
    assign a_rsp_valid=s_rsp_valid&&active&&!owner;
    assign b_rsp_valid=s_rsp_valid&&active&&owner;
    assign a_rsp_rdata=s_rsp_rdata;assign b_rsp_rdata=s_rsp_rdata;
    assign a_rsp_err=s_rsp_err;assign b_rsp_err=s_rsp_err;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            active<=0;owner<=0;owner_read<=0;prefer_b<=0;held_valid<=0;held_owner<=0;
        end else begin
            if(available&&s_cmd_valid&&!s_cmd_ready&&!held_valid) begin
                held_valid<=1;held_owner<=grant;
            end
            if(fire) begin
                held_valid<=0;owner<=grant;owner_read<=s_cmd_read;prefer_b<=!grant;
                active<=1'b1;
            end else if(retire) active<=0;
        end
    end
endmodule

module kwt_bank_overlap_sram(
    input wire clk,en,we,
    input wire [16:0] addr,stream_addr,
    input wire stream_write,result_write,
    input wire [16:0] result_addr,
    input wire [31:0] result_data,
    input wire [31:0] wdata,
    input wire [3:0] wmask,
    output wire [31:0] rdata
);
    wire [1023:0] bank_data;
    reg [4:0] read_bank;
    always @(posedge clk) if(en&&!we) read_bank<=addr[16:12];
    assign rdata=bank_data[read_bank*32+:32];
    for(genvar bank=0;bank<32;bank=bank+1) begin: banks
        wire stream_hit;
        if(bank==0||bank==1||bank==8||bank==9||bank==10) begin: stream_bank
            assign stream_hit=stream_write&&stream_addr[16:12]==5'(bank);
        end else begin: primary_only
            assign stream_hit=1'b0;
        end
        wire result_hit;
        if(bank>=4&&bank<=7) begin: result_bank
            assign result_hit=result_write&&result_addr[16:12]==5'(bank);
        end else begin: no_result
            assign result_hit=0;
        end
        wire bank_write=we||stream_hit||result_hit;
        wire [31:0] bank_wdata=result_hit?result_data:wdata;
        wire [3:0] bank_wmask=result_hit?4'hf:wmask;
        wire [11:0] bank_addr=result_hit?result_addr[11:0]:
            stream_hit?stream_addr[11:0]:addr[11:0];
        for(genvar half=0;half<2;half=half+1) begin: halves
            RAMSP4096X16 macro(
                .CLK(clk),.CEN(!((en&&addr[16:12]==5'(bank))||stream_hit||result_hit)),
                .GWEN(~bank_write),.WEN(~{{8{bank_write&&bank_wmask[half*2+1]}},{8{bank_write&&bank_wmask[half*2]}}}),
                .A(bank_addr),.D(bank_wdata[half*16+:16]),.Q(bank_data[bank*32+half*16+:16]),
                .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1)
            );
        end
    end
endmodule
