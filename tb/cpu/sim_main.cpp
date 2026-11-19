#include "Vkwt_cpu_soc.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <memory>
int main(int argc,char** argv) {
    std::setvbuf(stdout,nullptr,_IONBF,0);
    auto context=std::make_unique<VerilatedContext>();
    context->commandArgs(argc,argv);
    auto top=std::make_unique<Vkwt_cpu_soc>(context.get());
    top->clk=0; top->rst_n=0;
    uint64_t cycle=0;
    for(;cycle<300000000ULL && !context->gotFinish();++cycle) {
        top->rst_n=(cycle>=32);
        top->clk=0; top->eval(); context->timeInc(1);
        top->clk=1; top->eval(); context->timeInc(1);
        if(top->sim_done) break;
        if(cycle && cycle%2000000ULL==0)
            std::printf("CPU progress cycle=%llu pc=%08x\n",(unsigned long long)cycle,top->inspect_pc);
    }
    top->final();
    if(!top->sim_done || !top->sim_pass) {
        std::fprintf(stderr,"CPU integration failed or timed out: cycles=%llu pc=%08x\n",(unsigned long long)cycle,top->inspect_pc);
        return 1;
    }
    std::printf("PASS real E203 firmware integration: total_cycles=%llu\n",(unsigned long long)cycle);
    return 0;
}
