    integer ap_input_halves=0,ap_input_reads=0,ap_input_rows_complete=0;
    integer ap_input_single=0,ap_input_packed_low=0,ap_input_flush_high=0;
    integer ap_input_slot_changes=0,ap_input_last_read_slot=-1;
    reg ap_input_probe_pending=0;
    reg ap_input_probe_slot=0;
    reg [15:0] ap_input_probe_value=0;
    always @(posedge clk or negedge dut.core.rst_n) begin
        if(!dut.core.rst_n) begin
            ap_input_halves=0;ap_input_reads=0;ap_input_rows_complete=0;
            ap_input_single=0;ap_input_packed_low=0;ap_input_flush_high=0;
            ap_input_slot_changes=0;ap_input_last_read_slot=-1;
            ap_input_probe_pending=0;
        end else if(active) begin
            if(dut.pack_pending&&dut.pio_cmd_ready)
                $fatal(1,"INPUT_PENDING_PIO_ACCEPTED");
            if((dut.core.ap_input_rows[0].read_enable&&dut.core.ap_input_rows[0].write_enable)||
               (dut.core.ap_input_rows[1].read_enable&&dut.core.ap_input_rows[1].write_enable))
                $fatal(1,"INPUT_CURRENT_ROW_READ_WRITE_CONFLICT");
            if(dut.core.input_loading) begin
                if(dut.core.load_pair||dut.core.load_addr!=ap_input_halves||
                   dut.core.input_count!=ap_input_halves||dut.core.load_data!==inputs[ap_input_halves])
                    $fatal(1,"INPUT_HALF_ORDER_OR_VALUE at=%0d addr=%0d",ap_input_halves,dut.core.load_addr);
                if(dut.direct_load)ap_input_single=ap_input_single+1;
                if(dut.packed_load)ap_input_packed_low=ap_input_packed_low+1;
                if(dut.flush_high)ap_input_flush_high=ap_input_flush_high+1;
                if(dut.core.load_addr[5:0]==63)ap_input_rows_complete=ap_input_rows_complete+1;
                ap_input_halves=ap_input_halves+1;
            end
            ap_input_probe_pending=dut.core.ap_input_read;
            if(dut.core.ap_input_read) begin
                if(dut.core.input_count<(int'(dut.core.row)+1)*64)
                    $fatal(1,"INPUT_ROW_READ_BEFORE_FINAL_HALF");
                ap_input_probe_slot=dut.core.row[0];
                ap_input_probe_value=inputs[int'(dut.core.row)*64+int'(dut.core.request_inner)];
                if(ap_input_last_read_slot!=-1&&ap_input_last_read_slot!=int'(dut.core.row[0]))
                    ap_input_slot_changes=ap_input_slot_changes+1;
                ap_input_last_read_slot=int'(dut.core.row[0]);
                ap_input_reads=ap_input_reads+1;
            end
            if(dut.core.state==dut.core.B_MAC) begin
                if(dut.core.mac_a!==$signed({inputs[int'(dut.core.row)*64+int'(dut.core.inner)][15],
                                            inputs[int'(dut.core.row)*64+int'(dut.core.inner)]}))
                    $fatal(1,"INPUT_MAC_READ_ALIGNMENT row=%0d inner=%0d",dut.core.row,dut.core.inner);
            end
        end
    end
    always @(negedge clk) if(active&&dut.core.rst_n&&ap_input_probe_pending) begin
        if((ap_input_probe_slot?dut.core.ap_input_rdata[31:16]:dut.core.ap_input_rdata[15:0])!==ap_input_probe_value)
            $fatal(1,"INPUT_SYNCHRONOUS_READ_VALUE");
    end
