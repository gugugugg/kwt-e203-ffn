module kwt_ld_frontend(
    input wire clk,rst_n,soft_reset,input_ready,output_ready,layer_ready,
    input wire cpu_cmd_valid,output wire cpu_cmd_ready,input wire [7:0] cpu_cmd_addr,
    input wire cpu_cmd_read,input wire [31:0] cpu_cmd_wdata,input wire [3:0] cpu_cmd_wmask,
    output wire cpu_rsp_valid,input wire cpu_rsp_ready,output wire [31:0] cpu_rsp_rdata,output wire cpu_rsp_err,
    output wire pio_cmd_valid,input wire pio_cmd_ready,output wire [7:0] pio_cmd_addr,
    output wire pio_cmd_read,output wire [31:0] pio_cmd_wdata,output wire [3:0] pio_cmd_wmask,
    input wire pio_rsp_valid,output wire pio_rsp_ready,input wire [31:0] pio_rsp_rdata,input wire pio_rsp_err,
    output wire ld_cmd_valid,input wire ld_cmd_ready,output wire [31:0] ld_cmd_addr,
    output wire ld_cmd_read,output wire [31:0] ld_cmd_wdata,output wire [3:0] ld_cmd_wmask,
    input wire ld_rsp_valid,output wire ld_rsp_ready,input wire [31:0] ld_rsp_rdata,input wire ld_rsp_err,
    output wire error_sticky
);
    reg [31:0] address,words;
    reg csr_rsp_valid,csr_rsp_err;
    reg [31:0] csr_rsp_data;
    wire busy,done,dma_error;
    localparam [2:0] CH_IDLE=0,CH_INPUT=1,CH_LAYER=2,CH_KIND=3,CH_ADDR=4,CH_WEIGHT=5;
    reg [2:0] chain;
    reg chain_address,chain_words,chain_pending,chain_error;
    wire chain_pio=chain==CH_LAYER||chain==CH_KIND||chain==CH_ADDR;
    wire chain_busy=chain!=CH_IDLE;
    wire chain_enabled=chain==CH_INPUT&&chain_address&&chain_words&&!busy;
    wire [7:0] chain_pio_address=chain==CH_LAYER?8'h18:chain==CH_KIND?8'h08:8'h0c;
    wire [31:0] chain_pio_data=chain==CH_ADDR?32'd0:32'd1;
    wire csr=(cpu_cmd_addr==8'h40)||(cpu_cmd_addr==8'h44)||(cpu_cmd_addr==8'h48)||
             (cpu_cmd_addr==8'h4c)||(cpu_cmd_addr==8'h50);
    wire csr_slot=!csr_rsp_valid||cpu_rsp_ready;
    wire csr_ready=csr_slot&&(!(cpu_cmd_read&&cpu_cmd_addr==8'h50)||!(busy||chain_busy));
    wire csr_fire=cpu_cmd_valid&&csr&&csr_ready;
    wire valid_command=(cpu_cmd_wdata==1)||(cpu_cmd_wdata==2)||
        (cpu_cmd_wdata==3&&words==32'd384);
    wire cpu_launch=csr_fire&&!cpu_cmd_read&&cpu_cmd_wmask==4'hf&&cpu_cmd_addr==8'h48&&!(busy||chain_busy)&&valid_command;
    wire launch=cpu_launch||chain==CH_WEIGHT;
    wire [31:0] status={29'd0,dma_error||chain_error,done,busy||chain_busy};
    assign error_sticky=dma_error||chain_error;
    wire a_cmd_ready,a_rsp_valid,a_rsp_err;
    wire [31:0] a_rsp_data;
    wire dma_pio_cmd_valid,dma_pio_cmd_ready,dma_pio_cmd_read,dma_pio_rsp_valid,dma_pio_rsp_ready,dma_pio_rsp_err;
    wire [7:0] dma_pio_cmd_addr;
    wire [31:0] dma_pio_cmd_wdata,dma_pio_rsp_rdata;
    wire [3:0] dma_pio_cmd_wmask;
    assign cpu_cmd_ready=csr?csr_ready:(!chain_pio&&csr_slot&&a_cmd_ready);
    assign cpu_rsp_valid=csr_rsp_valid||(!chain_pio&&a_rsp_valid);
    assign cpu_rsp_rdata=csr_rsp_valid?csr_rsp_data:a_rsp_data;
    assign cpu_rsp_err=csr_rsp_valid?csr_rsp_err:a_rsp_err;
    kwt_ld_icb_arbiter #(.AW(8)) core_arbiter(
        .clk(clk),.rst_n(rst_n),
        .a_cmd_valid(chain_pio?!chain_pending:cpu_cmd_valid&&!csr&&csr_slot),
        .a_cmd_ready(a_cmd_ready),.a_cmd_addr(chain_pio?chain_pio_address:cpu_cmd_addr),
        .a_cmd_read(!chain_pio&&cpu_cmd_read),.a_cmd_wdata(chain_pio?chain_pio_data:cpu_cmd_wdata),
        .a_cmd_wmask(chain_pio?4'hf:cpu_cmd_wmask),
        .a_rsp_valid(a_rsp_valid),.a_rsp_ready(chain_pio||(cpu_rsp_ready&&!csr_rsp_valid)),
        .a_rsp_rdata(a_rsp_data),.a_rsp_err(a_rsp_err),
        .b_cmd_valid(dma_pio_cmd_valid),.b_cmd_ready(dma_pio_cmd_ready),.b_cmd_addr(dma_pio_cmd_addr),
        .b_cmd_read(dma_pio_cmd_read),.b_cmd_wdata(dma_pio_cmd_wdata),.b_cmd_wmask(dma_pio_cmd_wmask),
        .b_rsp_valid(dma_pio_rsp_valid),.b_rsp_ready(dma_pio_rsp_ready),.b_rsp_rdata(dma_pio_rsp_rdata),.b_rsp_err(dma_pio_rsp_err),
        .s_cmd_valid(pio_cmd_valid),.s_cmd_ready(pio_cmd_ready),.s_cmd_addr(pio_cmd_addr),
        .s_cmd_read(pio_cmd_read),.s_cmd_wdata(pio_cmd_wdata),.s_cmd_wmask(pio_cmd_wmask),
        .s_rsp_valid(pio_rsp_valid),.s_rsp_ready(pio_rsp_ready),.s_rsp_rdata(pio_rsp_rdata),.s_rsp_err(pio_rsp_err));
    kwt_ld_engine loading_dma(
        .clk(clk),.rst_n(rst_n&&!soft_reset),.start(launch),.direction(cpu_launch&&cpu_cmd_wdata==2),
        .start_address(address),.word_count(words),.busy(busy),.done(done),.error(dma_error),
        .input_ready(input_ready),.output_ready(output_ready),
        .mem_cmd_valid(ld_cmd_valid),.mem_cmd_ready(ld_cmd_ready),.mem_cmd_addr(ld_cmd_addr),
        .mem_cmd_read(ld_cmd_read),.mem_cmd_wdata(ld_cmd_wdata),.mem_cmd_wmask(ld_cmd_wmask),
        .mem_rsp_valid(ld_rsp_valid),.mem_rsp_ready(ld_rsp_ready),.mem_rsp_rdata(ld_rsp_rdata),.mem_rsp_err(ld_rsp_err),
        .pio_cmd_valid(dma_pio_cmd_valid),.pio_cmd_ready(dma_pio_cmd_ready),.pio_cmd_addr(dma_pio_cmd_addr),
        .pio_cmd_read(dma_pio_cmd_read),.pio_cmd_wdata(dma_pio_cmd_wdata),.pio_cmd_wmask(dma_pio_cmd_wmask),
        .pio_rsp_valid(dma_pio_rsp_valid),.pio_rsp_ready(dma_pio_rsp_ready),.pio_rsp_rdata(dma_pio_rsp_rdata),.pio_rsp_err(dma_pio_rsp_err));
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin address<=0;words<=0;csr_rsp_valid<=0;csr_rsp_err<=0;csr_rsp_data<=0;end
        else begin
            if(soft_reset)begin address<=0;words<=0;end
            if(csr_rsp_valid&&cpu_rsp_ready)csr_rsp_valid<=0;
            if(csr_fire)begin
                csr_rsp_valid<=1;csr_rsp_err<=0;csr_rsp_data<=0;
                if(cpu_cmd_read)case(cpu_cmd_addr)
                    8'h40:csr_rsp_data<=address;
                    8'h44:csr_rsp_data<=words;
                    default:csr_rsp_data<=status;
                endcase
                else if(cpu_cmd_wmask!=4'hf)csr_rsp_err<=1;
                else case(cpu_cmd_addr)
                    8'h40:address<=cpu_cmd_wdata;
                    8'h44:words<=cpu_cmd_wdata;
                    8'h48:if(busy||chain_busy||!valid_command)csr_rsp_err<=1;
                    default:csr_rsp_err<=1;
                endcase
            end
        end
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            chain<=CH_IDLE;chain_address<=0;chain_words<=0;chain_pending<=0;chain_error<=0;
        end else if(soft_reset)begin
            chain<=CH_IDLE;chain_address<=0;chain_words<=0;chain_pending<=0;chain_error<=0;
        end else begin
            if(cpu_launch)begin
                chain_error<=0;
                if(cpu_cmd_wdata==3)begin
                    chain<=CH_INPUT;chain_address<=0;chain_words<=0;
                end
            end
            if(chain==CH_INPUT)begin
                if(csr_fire&&!cpu_cmd_read&&cpu_cmd_wmask==4'hf)begin
                    if(cpu_cmd_addr==8'h40)chain_address<=1;
                    if(cpu_cmd_addr==8'h44)chain_words<=1;
                end
                if(chain_enabled)begin
                    if(dma_error)chain<=CH_IDLE;
                    else if(layer_ready)chain<=CH_LAYER;
                end
            end
            if(chain_pio)begin
                if(!chain_pending&&a_cmd_ready)chain_pending<=1;
                if(a_rsp_valid)begin
                    chain_pending<=0;
                    if(a_rsp_err)begin chain_error<=1;chain<=CH_IDLE;end
                    else chain<=chain+3'd1;
                end
            end
            if(chain==CH_WEIGHT)chain<=CH_IDLE;
        end
    end
endmodule
