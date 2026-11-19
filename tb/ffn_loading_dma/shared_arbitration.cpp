#include "Vkwt_shared_icb_sm40.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <stdexcept>
int main(){
    try{
        VerilatedContext context;Vkwt_shared_icb_sm40 t{&context};unsigned cycles=0;
        auto tick=[&](){t.clk=0;t.eval();t.clk=1;t.eval();context.timeInc(1);++cycles;};
        t.rst_n=0;t.cpu_cmd_valid=0;t.ld_cmd_valid=0;t.host_cmd_valid=0;t.cpu_rsp_ready=1;t.ld_rsp_ready=1;t.host_rsp_ready=1;
        for(int i=0;i<4;++i)tick();t.rst_n=1;
        t.host_cmd_read=0;t.host_cmd_wmask=15;t.host_cmd_valid=1;
        for(unsigned i=0;i<4;++i){
            t.host_cmd_addr=i;t.host_cmd_wdata=0x11110000u+i;t.clk=0;t.eval();
            while(!t.host_cmd_ready)tick();tick();
        }
        t.host_cmd_valid=0;
        unsigned count[2]={0,0};bool waiting[2]={false,false};
        while(count[0]<20||count[1]<20){
            unsigned address[2];bool read[2];uint32_t value[2];
            for(unsigned m=0;m<2;++m){
                unsigned n=count[m];read[m]=n<4||((n-4)&1);unsigned index=n<4?n:(m?128:64)+(n-4)/2;
                address[m]=0xa0000000u+index*4;value[m]=(n<4?0x11110000u:(m?0xdcba0000u:0xabcd0000u))+(n<4?n:(n-4)/2);
            }
            t.cpu_cmd_valid=count[0]<20&&!waiting[0];t.cpu_cmd_addr=address[0];t.cpu_cmd_read=read[0];t.cpu_cmd_wdata=value[0];t.cpu_cmd_wmask=15;
            t.ld_cmd_valid=count[1]<20&&!waiting[1];t.ld_cmd_addr=address[1];t.ld_cmd_read=read[1];t.ld_cmd_wdata=value[1];t.ld_cmd_wmask=15;
            t.cpu_rsp_ready=cycles%7>1;t.ld_rsp_ready=1;t.clk=0;t.eval();
            bool command[2]={bool(t.cpu_cmd_valid&&t.cpu_cmd_ready),bool(t.ld_cmd_valid&&t.ld_cmd_ready)};
            bool response[2]={bool(t.cpu_rsp_valid&&t.cpu_rsp_ready),bool(t.ld_rsp_valid&&t.ld_rsp_ready)};
            uint32_t result[2]={t.cpu_rsp_rdata,t.ld_rsp_rdata};bool error[2]={bool(t.cpu_rsp_err),bool(t.ld_rsp_err)};
            t.clk=1;t.eval();context.timeInc(1);++cycles;
            for(unsigned m=0;m<2;++m){
                if(command[m])waiting[m]=true;
                if(response[m]){
                    if(!waiting[m]||error[m]||(read[m]&&result[m]!=value[m]))throw std::runtime_error("Shared-memory response ownership or data mismatch");
                    waiting[m]=false;++count[m];
                }
            }
        }
        std::printf("SHARED_DMA_NORMAL_ARBITRATION_PASS cpu=%u dma=%u cycles=%u\n",count[0],count[1],cycles);
        return 0;
    }catch(const std::exception& e){std::fprintf(stderr,"%s\n",e.what());return 1;}
}
