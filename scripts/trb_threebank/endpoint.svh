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
    assign ld_cmd_read=1;
    assign ld_cmd_wdata=0;
    assign ld_cmd_wmask=0;

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
    kwt_threebank_core core(.*);
endmodule

