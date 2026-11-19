module kwt_ld_engine(
    input wire clk,rst_n,start,direction,
    input wire [31:0] start_address,word_count,
    output wire busy,output reg done,error,
    input wire input_ready,output_ready,
    output wire mem_cmd_valid,input wire mem_cmd_ready,
    output wire [31:0] mem_cmd_addr,output wire mem_cmd_read,
    output wire [31:0] mem_cmd_wdata,output wire [3:0] mem_cmd_wmask,
    input wire mem_rsp_valid,output wire mem_rsp_ready,
    input wire [31:0] mem_rsp_rdata,input wire mem_rsp_err,
    output wire pio_cmd_valid,input wire pio_cmd_ready,
    output wire [7:0] pio_cmd_addr,output wire pio_cmd_read,
    output wire [31:0] pio_cmd_wdata,output wire [3:0] pio_cmd_wmask,
    input wire pio_rsp_valid,output wire pio_rsp_ready,
    input wire [31:0] pio_rsp_rdata,input wire pio_rsp_err
);
    localparam [2:0] IDLE=0,MEM_REQ=1,MEM_RSP=2,PIO_REQ=3,PIO_RSP=4;
    reg [2:0] state;
    reg output_transfer;
    reg [31:0] address,remaining,buffer;
    assign busy=state!=IDLE;
    assign mem_cmd_valid=state==MEM_REQ;
    assign mem_cmd_addr=address;
    assign mem_cmd_read=!output_transfer;
    assign mem_cmd_wdata=buffer;assign mem_cmd_wmask=4'hf;
    assign mem_rsp_ready=(state==MEM_REQ)||(state==MEM_RSP);
    assign pio_cmd_valid=(state==PIO_REQ)&&(output_transfer?output_ready:input_ready);
    assign pio_cmd_addr=output_transfer?8'h34:8'h30;
    assign pio_cmd_read=output_transfer;
    assign pio_cmd_wdata=buffer;assign pio_cmd_wmask=4'hf;
    assign pio_rsp_ready=(state==PIO_REQ)||(state==PIO_RSP);
    wire mem_fire=mem_cmd_valid&&mem_cmd_ready;
    wire pio_fire=pio_cmd_valid&&pio_cmd_ready;
    wire mem_complete=mem_rsp_valid&&mem_rsp_ready&&((state==MEM_RSP)||mem_fire);
    wire pio_complete=pio_rsp_valid&&pio_rsp_ready&&((state==PIO_RSP)||pio_fire);
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin state<=IDLE;done<=0;error<=0;address<=0;remaining<=0;buffer<=0;output_transfer<=0;end
        else begin
            if(start)begin
                done<=0;error<=0;address<=start_address;remaining<=word_count;output_transfer<=direction;
                if(word_count==0)begin done<=1;state<=IDLE;end
                else state<=direction?PIO_REQ:MEM_REQ;
            end else begin
                if(mem_fire&&!mem_complete)state<=MEM_RSP;
                if(pio_fire&&!pio_complete)state<=PIO_RSP;
                if(mem_complete)begin
                    if(mem_rsp_err)begin error<=1;done<=1;state<=IDLE;end
                    else if(!output_transfer)begin buffer<=mem_rsp_rdata;state<=PIO_REQ;end
                    else if(remaining==1)begin remaining<=0;done<=1;state<=IDLE;end
                    else begin remaining<=remaining-1;address<=address+4;state<=PIO_REQ;end
                end
                if(pio_complete)begin
                    if(pio_rsp_err)begin error<=1;done<=1;state<=IDLE;end
                    else if(output_transfer)begin buffer<=pio_rsp_rdata;state<=MEM_REQ;end
                    else if(remaining==1)begin remaining<=0;done<=1;state<=IDLE;end
                    else begin remaining<=remaining-1;address<=address+4;state<=MEM_REQ;end
                end
            end
        end
    end
endmodule
