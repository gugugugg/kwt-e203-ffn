// Shared loading-side correction and the three-macro row store.
module correction_probe(
    input wire clk,rst_n,weight_mode,
    input wire [7:0] lanes,first,last,
    input wire [55:0] addresses,
    input wire [127:0] even_data,odd_data,
    input wire [255:0] original_bias,
    input wire row_read,
    input wire [6:0] row_address,
    input wire [2:0] cache_index,
    input wire [5:0] bias_col0,bias_col1,
    output wire [71:0] adjusted_bias,
    output wire [287:0] cached_rows,
    output wire [3:0] queued
);
    reg signed [35:0] row_sums [0:7];
    reg signed [35:0] column_sums [0:7][0:7];
    reg [42:0] fifo [0:7];
    reg [2:0] head,tail;
    reg [3:0] count;
    wire drain=count!=0;
    assign queued=count;
    wire [3:0] push_count;
    wire [7:0] complete_row=weight_mode?8'b0:(lanes&last);
    reg [35:0] cache [0:7];
    wire [47:0] read_value;
    reg pending;
    reg [2:0] pending_index;
    wire [6:0] store_address=drain?fifo[head][42:36]:row_address;
    wire [47:0] store_data={12'd0,fifo[head][35:0]};
    assign adjusted_bias={column_sums[bias_col1[2:0]][bias_col1[5:3]],
                          column_sums[bias_col0[2:0]][bias_col0[5:3]]};

    reg [3:0] pushes;
    always_comb begin
        pushes=0;
        for(integer i=0;i<8;i=i+1) pushes=pushes+{3'b0,complete_row[i]};
    end
    assign push_count=pushes;
    wire [287:0] updated;
    for(genvar lane=0;lane<8;lane=lane+1) begin: correction
        wire [6:0] id=addresses[7*lane+:7];
        wire signed [31:0] p=$signed(even_data[lane*16+:16])*$signed(odd_data[lane*16+:16]);
        wire signed [31:0] b=$signed(original_bias[lane*32+:32]);
        wire signed [35:0] prior=weight_mode?
            (first[lane]?{{4{b[31]}},b}:column_sums[lane][id[5:3]]):
            (first[lane]?36'sd0:row_sums[lane]);
        assign updated[lane*36+:36]=prior-{{4{p[31]}},p};
    end

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin head<=0;tail<=0;count<=0;pending<=0;pending_index<=0;end
        else begin
            if(drain) head<=head+3'd1;
            tail<=tail+push_count[2:0];
            count<=count+push_count-{3'b0,drain};
            pending<=row_read&&!drain;
            if(row_read&&!drain) pending_index<=cache_index;
        end
    end

    always @(posedge clk) begin
        integer fifo_offset;
        fifo_offset=0;
        for(integer lane=0;lane<8;lane=lane+1) begin
            if(lanes[lane]) begin
                if(weight_mode)
                    column_sums[lane][addresses[7*lane+3+:3]]<=updated[lane*36+:36];
                else
                    row_sums[lane]<=updated[lane*36+:36];
            end
            if(complete_row[lane]) begin
                fifo[3'(tail+fifo_offset)]<={addresses[7*lane+:7],updated[lane*36+:36]};
                fifo_offset=fifo_offset+1;
            end
        end
        if(pending) cache[pending_index]<=read_value[35:0];
    end

    for(genvar part=0;part<3;part=part+1) begin: store
        RAMSP128X16 mem(.CLK(clk),.CEN(!(drain||row_read)),.GWEN(!drain),
            .WEN({16{!drain}}),.A(store_address),.D(store_data[16*part+:16]),
            .Q(read_value[16*part+:16]),.EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
    end
    for(genvar row=0;row<8;row=row+1) begin: cache_out
        assign cached_rows[36*row+:36]=cache[row];
    end
endmodule

