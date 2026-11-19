    always @(posedge dut.soft_reset) ah_soft_resets=ah_soft_resets+1;
    generate for(genvar ah_lane=0;ah_lane<32;ah_lane++) begin: ah_equiv
        localparam integer ah_row=ah_lane/16;
        localparam integer ah_col=ah_lane%16;
        wire gclk=dut.core.jp_mac_lanes[ah_lane].accumulator_clk;
        wire seed=dut.core.jp_seed_mask[ah_lane];
        wire mac=dut.core.jp_mac_mask[ah_lane];
        wire consume=dut.core.jp_quant_mask[ah_lane];
        wire signed [16:0] activation=$signed(dut.core.jp_input_return[(ah_row*2+ah_col/8)*16+:16]);
        wire signed [15:0] weight_value=$signed(dut.core.pm_rdata[ah_col*16+:16]);
        reg signed [35:0] sr_acc;
        reg seeded=0;
        reg expect_edge;
        reg check_edge;
        always @(posedge gclk) begin
            if(seed) sr_acc<=36'($signed(dut.core.bias_pair[(ah_col%2)*64+:64]));
            else if(mac) sr_acc<=sr_acc+36'(activation*weight_value);
        end
        always @(posedge clk or negedge dut.core.rst_n) begin
            if(!dut.core.rst_n) seeded<=0;
            else if(dut.core.layer_start_valid&&dut.core.layer_start_ready) seeded<=0;
            else begin
                if((mac||consume) && (!seeded || (^sr_acc===1'bx) ||
                    sr_acc!==dut.core.accumulator[ah_lane]))
                    $fatal(1,"AH invalid or unequal MAC/quant lane=%0d row=%0d",ah_lane,dut.core.row);
                if(seeded && sr_acc!==dut.core.accumulator[ah_lane])
                    $fatal(1,"AH valid state mismatch lane=%0d row=%0d",ah_lane,dut.core.row);
                if(seed) seeded<=1;
                if(ah_row==1 && dut.core.row==98 && (mac||consume||seed))
                    $fatal(1,"AH row98 second lane enabled");
            end
        end
        always @(posedge clk) begin
            check_edge=dut.core.rst_n;
            expect_edge=seed||mac;
            #0.001;
            if(check_edge && dut.core.rst_n && gclk!==expect_edge)
                $fatal(1,"AH ICG edge qualification lane=%0d",ah_lane);
        end
    end endgenerate

