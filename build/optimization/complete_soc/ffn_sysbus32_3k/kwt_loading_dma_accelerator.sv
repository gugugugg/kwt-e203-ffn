module kwt_encoder_accelerator(
    input wire clk,rst_n,
    input wire icb_cmd_valid,
    output wire icb_cmd_ready,
    input wire [7:0] icb_cmd_addr,
    input wire icb_cmd_read,
    input wire [31:0] icb_cmd_wdata,
    input wire [3:0] icb_cmd_wmask,
    output wire icb_rsp_valid,
    input wire icb_rsp_ready,
    output wire [31:0] icb_rsp_rdata,
    output wire icb_rsp_err
,
    output wire ld_cmd_valid,
    input wire ld_cmd_ready,
    output wire [31:0] ld_cmd_addr,
    output wire ld_cmd_read,
    output wire [31:0] ld_cmd_wdata,
    output wire [3:0] ld_cmd_wmask,
    input wire ld_rsp_valid,
    output wire ld_rsp_ready,
    input wire [31:0] ld_rsp_rdata,
    input wire [11:0] input_committed,
    input wire [13:0] parameter_committed,
    input wire ld_rsp_err
);
    wire busy,done,error;
    reg stage_ready;
    reg response;
    reg [31:0] response_data;
    wire write_command=icb_cmd_valid&&icb_cmd_ready&&!icb_cmd_read;
    wire start=write_command&&icb_cmd_addr==8'h48&&icb_cmd_wdata[0]&&icb_cmd_wmask[0]&&!busy;
    assign icb_cmd_ready=(!response||icb_rsp_ready)&&
        !(icb_cmd_read&&icb_cmd_addr==8'h50&&busy);
    assign icb_rsp_valid=response;
    assign icb_rsp_rdata=response_data;
    assign icb_rsp_err=0;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin response<=0;stage_ready<=0;end
        else begin
            if(icb_cmd_valid&&icb_cmd_ready) response<=1;
            else if(icb_rsp_ready) response<=0;
            if(write_command&&icb_cmd_addr==0&&icb_cmd_wmask[0])
                stage_ready<=icb_cmd_wdata[0]&&!icb_cmd_wdata[1];
        end
    end
    always @(posedge clk) if(icb_cmd_valid&&icb_cmd_ready) begin
        response_data<=0;
        if(icb_cmd_read) case(icb_cmd_addr)
            8'h04: response_data<={24'd0,error,done,2'b0,!busy,3'b0};
            8'h24: response_data<={24'd0,error,2'b0,stage_ready,4'b0};
            8'h28: response_data<=32'h4b574531;
            8'h50: response_data<={29'd0,error,done,busy};
            default: ;
        endcase
    end
    wire src_valid,src_ready,src_rsp,src_rsp_ready,output_priority;
    wire wb_valid,wb_ready,wb_ack_valid,wb_ack_ready;
    wire [16:0] wb_addr;
    wire [31:0] wb_data,src_addr;
    kwt_threebank_core core(.clk(clk),.rst_n(rst_n),.start(start),.busy(busy),.done(done),.error(error),
        .input_committed(input_committed),.parameter_committed(parameter_committed),.output_priority(output_priority),
        .ld_cmd_valid(src_valid),.ld_cmd_ready(src_ready),.ld_cmd_addr(src_addr),
        .ld_rsp_valid(src_rsp),.ld_rsp_ready(src_rsp_ready),.ld_rsp_rdata(ld_rsp_rdata),.ld_rsp_err(ld_rsp_err),
        .wb_valid(wb_valid),.wb_ready(wb_ready),.wb_addr(wb_addr),.wb_data(wb_data),
        .wb_ack_valid(wb_ack_valid),.wb_ack_ready(wb_ack_ready));
    kwt_sysbus_issue issue_bus(.clk(clk),.rst_n(rst_n),.start(start),
        .source_valid(src_valid),.source_ready(src_ready),.source_addr(src_addr),
        .source_rsp_valid(src_rsp),.source_rsp_ready(src_rsp_ready),
        .result_valid(wb_valid),.result_ready(wb_ready),.result_addr(wb_addr),.result_data(wb_data),
        .result_ack(wb_ack_valid),.result_ack_ready(wb_ack_ready),.output_priority(output_priority),
        .ld_cmd_valid(ld_cmd_valid),.ld_cmd_read(ld_cmd_read),.ld_cmd_ready(ld_cmd_ready),
        .ld_cmd_addr(ld_cmd_addr),.ld_cmd_wdata(ld_cmd_wdata),.ld_cmd_wmask(ld_cmd_wmask),
        .ld_rsp_valid(ld_rsp_valid),.ld_rsp_ready(ld_rsp_ready));
endmodule

