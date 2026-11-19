"""Observe seed lifetimes and DMA event conservation without adding hardware state."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c_energy import observers as previous

def mechanism(core,window,reset,hardware):
    text=''
    if 'AR' in hardware:
        text+='''
`ifndef KWT_UNIFIED_GATE
    generate for(genvar car_lane=0;car_lane<32;car_lane=car_lane+1)begin: car_seed_lifecycle
        reg seeded=0;
        integer macs=0;
        always @(posedge CORE.clk or negedge RESET)begin
            if(!RESET)begin seeded=0;macs=0;end
            else if(CORE.layer_start_valid&&CORE.layer_start_ready)begin seeded=0;macs=0;end
            else if(WINDOW)begin
                if(CORE.jp_quant_mask[car_lane])begin
                    if(!seeded||macs!=64)$fatal(1,"AREA_AR_QUANT_WITHOUT_SEED lane=%0d macs=%0d",car_lane,macs);
                    seeded=0;macs=0;
                end
                if(CORE.jp_seed_mask[car_lane])begin seeded=1;macs=0;end
                else if(CORE.jp_mac_mask[car_lane])begin
                    if(!seeded)$fatal(1,"AREA_AR_MAC_WITHOUT_SEED lane=%0d",car_lane);
                    macs=macs+1;
                end
            end
        end
    end endgenerate
`endif
'''
    if 'D1' in hardware:
        engine=core.rsplit('.core',1)[0]+'.dma_frontend.loading_dma'
        text+='''
`ifndef KWT_UNIFIED_GATE
    reg [31:0] car_reference_destination=0;
    always @(posedge ENG.clk or negedge ENG.rst_n)begin
        if(!ENG.rst_n)car_reference_destination=0;
        else if(ENG.start)car_reference_destination=ENG.word_count;
        else if(ENG.pd_active)begin
            if({1'b0,car_reference_destination}!==({1'b0,ENG.source_remaining}+{31'd0,ENG.pd_count}))
                $fatal(1,"AREA_D1_CONSERVATION");
            if(ENG.dest_complete)begin
                if((car_reference_destination==1)!=(ENG.source_remaining==0&&ENG.pd_count==1))
                    $fatal(1,"AREA_D1_LAST_RESPONSE");
                car_reference_destination=car_reference_destination-1;
            end
        end
    end
`endif
'''.replace('ENG',engine)
    return text.replace('CORE',core).replace('WINDOW',window).replace('RESET',reset)

def commit_observer(core,window,reset,hardware=None):
    return previous.commit_observer(core,window,reset)+mechanism(core,window,reset,hardware or [])

def adapt_native_bench(text,hardware=None):
    text=previous.adapt_native_bench(text)
    at=text.rfind('endmodule');return text[:at]+mechanism('dut.core','active','dut.core.rst_n',hardware or [])+text[at:]

def adapt_cpu_bench(text,core,hardware=None):
    text=previous.adapt_cpu_bench(text,core)
    at=text.rfind('endmodule');return text[:at]+mechanism(core,'activity_window',core+'.rst_n',hardware or [])+text[at:]
