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
    reg pd_active,output_transfer;
    reg [31:0] address,source_remaining,dest_remaining;
    reg [31:0] pd_slot[0:1];
    reg [1:0] pd_valid,pd_count;
    reg pd_write,pd_read,pd_source_slot;
    reg pd_source_pending,pd_dest_pending;
    wire source_ready=output_transfer?pio_cmd_ready:mem_cmd_ready;
    wire source_rsp_valid=output_transfer?pio_rsp_valid:mem_rsp_valid;
    wire [31:0] source_data=output_transfer?pio_rsp_rdata:mem_rsp_rdata;
    wire source_error=output_transfer?pio_rsp_err:mem_rsp_err;
    wire dest_ready=output_transfer?mem_cmd_ready:pio_cmd_ready;
    wire dest_rsp_valid=output_transfer?mem_rsp_valid:pio_rsp_valid;
    wire dest_error=output_transfer?mem_rsp_err:pio_rsp_err;
    wire memory_dest_valid=pd_active&&output_transfer&&!error&&pd_valid[pd_read];
    wire pio_dest_valid=pd_active&&!output_transfer&&!error&&pd_valid[pd_read]&&
        !pd_dest_pending&&input_ready;
    wire memory_dest_complete=pd_active&&output_transfer&&mem_rsp_valid&&
        (pd_dest_pending||(memory_dest_valid&&mem_cmd_ready));
    wire pio_dest_complete=pd_active&&!output_transfer&&pio_rsp_valid&&
        (pd_dest_pending||(pio_dest_valid&&pio_cmd_ready));
    wire dest_valid=memory_dest_valid||pio_dest_valid;
    wire dest_fire=dest_valid&&dest_ready;
    wire dest_complete=pd_active&&dest_rsp_valid&&(pd_dest_pending||dest_fire);
    wire memory_source_valid=pd_active&&!output_transfer&&!error&&(source_remaining!=0)&&
        ((pd_count<2)||
         (pd_count==2&&((address>=32'ha0020000&&address<32'ha0028800)||
                        (address>=32'ha0000000&&address<32'ha0003180))&&
          address[1:0]==2'b00&&pio_dest_complete&&!pio_rsp_err));
    wire pio_source_valid=pd_active&&output_transfer&&!error&&(source_remaining!=0)&&
        !pd_source_pending&&output_ready&&
        ((pd_count<2)||
         (pd_count==2&&pd_dest_pending&&mem_rsp_valid&&!mem_rsp_err&&
          address>=32'ha0010004&&address<=32'ha001c600&&address[1:0]==2'b00));
    wire source_valid=memory_source_valid||pio_source_valid;
    wire source_fire=source_valid&&source_ready;
    wire source_complete=pd_active&&source_rsp_valid&&(pd_source_pending||source_fire);
    wire source_pending_next=(pd_source_pending||source_fire)&&!source_complete||
        (pd_source_pending&&source_complete&&source_fire);
    wire dest_pending_next=(pd_dest_pending||dest_fire)&&!dest_complete||
        (pd_dest_pending&&dest_complete&&dest_fire);
    wire failed=(source_complete&&source_error)||(dest_complete&&dest_error);
    assign busy=pd_active;
    assign mem_cmd_valid=memory_dest_valid||memory_source_valid;
    assign mem_cmd_addr=address;
    assign mem_cmd_read=!output_transfer;
    assign mem_cmd_wdata=pd_slot[pd_read];
    assign mem_cmd_wmask=4'hf;
    assign mem_rsp_ready=pd_active;
    assign pio_cmd_valid=pio_source_valid||pio_dest_valid;
    assign pio_cmd_addr=output_transfer?8'h34:8'h30;
    assign pio_cmd_read=output_transfer;
    assign pio_cmd_wdata=pd_slot[pd_read];
    assign pio_cmd_wmask=4'hf;
    assign pio_rsp_ready=pd_active;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            pd_active<=0;output_transfer<=0;done<=0;error<=0;address<=0;
            source_remaining<=0;dest_remaining<=0;pd_count<=0;pd_valid<=0;
            pd_write<=0;pd_read<=0;pd_source_slot<=0;pd_source_pending<=0;pd_dest_pending<=0;
            pd_slot[0]<=0;pd_slot[1]<=0;
        end else if(start)begin
            pd_active<=word_count!=0;done<=word_count==0;error<=0;output_transfer<=direction;
            address<=start_address;source_remaining<=word_count;dest_remaining<=word_count;
            pd_count<=0;pd_valid<=0;pd_write<=0;pd_read<=0;pd_source_slot<=0;
            pd_source_pending<=0;pd_dest_pending<=0;
        end else if(pd_active)begin
            pd_source_pending<=source_pending_next;pd_dest_pending<=dest_pending_next;
            pd_count<=pd_count+2'(source_fire)-2'(dest_complete);
            if(mem_cmd_valid&&mem_cmd_ready)address<=address+4;
            if(dest_fire)begin pd_valid[pd_read]<=0;pd_read<=!pd_read;end
            if(source_fire)begin
                source_remaining<=source_remaining-1;pd_source_slot<=pd_write;pd_write<=!pd_write;
            end
            if(source_complete)begin
                pd_slot[pd_source_pending?pd_source_slot:pd_write]<=source_data;
                pd_valid[pd_source_pending?pd_source_slot:pd_write]<=1;
            end
            if(dest_complete)begin
                dest_remaining<=dest_remaining-1;
                if(dest_remaining==1)begin pd_active<=0;done<=1;end
            end
            if(failed||error)begin
                error<=1;
                if(!source_pending_next&&!dest_pending_next)begin
                    pd_active<=0;done<=1;pd_valid<=0;pd_count<=0;
                end
            end
        end
    end
endmodule
