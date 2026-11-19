 /*                                                                      
 Copyright 2018-2020 Nuclei System Technology, Inc.                
                                                                         
 Licensed under the Apache License, Version 2.0 (the "License");         
 you may not use this file except in compliance with the License.        
 You may obtain a copy of the License at                                 
                                                                         
     http://www.apache.org/licenses/LICENSE-2.0                          
                                                                         
  Unless required by applicable law or agreed to in writing, software    
 distributed under the License is distributed on an "AS IS" BASIS,       
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and     
 limitations under the License.                                          
 */                                                                      
                                                                         
                                                                         
                                                                         
//=====================================================================
//
// Designer   : Bob Hu
//
// Description:
//  The module is to control the mask ROM 
//
// ====================================================================

module sirv_mrom_top #(
    parameter AW = 12,
    parameter DW = 32,
    parameter DP = 1024
)(
  //    * Bus cmd channel
  input  rom_icb_cmd_valid, // Handshake valid
  output rom_icb_cmd_ready, // Handshake ready
  input  [AW-1:0] rom_icb_cmd_addr, // Bus transaction start addr 
  input  rom_icb_cmd_read,   // Read or write

  //    * Bus RSP channel
  output rom_icb_rsp_valid, // Response valid 
  input  rom_icb_rsp_ready, // Response ready
  output rom_icb_rsp_err,   // Response error
  output [DW-1:0] rom_icb_rsp_rdata, 

  input  clk,
  input  rst_n
  );
reg pending,rsp_valid,rsp_error;
reg [DW-1:0] rsp_data;
wire [DW-1:0] rom_dout;
wire fire=rom_icb_cmd_valid&&rom_icb_cmd_ready;
assign rom_icb_cmd_ready=!pending&&!rsp_valid;
assign rom_icb_rsp_valid=rsp_valid;
assign rom_icb_rsp_err=rsp_error;
assign rom_icb_rsp_rdata=rsp_data;
ROM1KX32 u_sirv_mrom(
    .CENY(),.AY(),.Q(rom_dout),.CLK(clk),.CEN(!(fire&&rom_icb_cmd_read)),
    .A(rom_icb_cmd_addr[AW-1:2]),.EMA(3'h2),.TEN(1'b1),.BEN(1'b1),
    .TCEN(1'b1),.TA(10'b0),.TQ(32'b0),.PGEN(1'b0),.KEN(1'b1));
always @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin pending<=0;rsp_valid<=0;rsp_error<=0;rsp_data<=0;end
    else begin
        if(rsp_valid&&rom_icb_rsp_ready) rsp_valid<=0;
        if(fire) begin pending<=1;rsp_error<=!rom_icb_cmd_read;end
        if(pending) begin pending<=0;rsp_valid<=1;rsp_data<=rom_dout;end
    end
end
endmodule
