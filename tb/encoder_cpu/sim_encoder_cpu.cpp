#include "Vkwt_encoder_cpu_soc.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
// The model's actual stage order has FC1/GELU at stage 9/10.
struct TraceChecker {
    size_t offsets[14]{},per_layer=0,received=0;
    int task=-1;
    bool started=false;
    std::vector<int64_t> expected,actual;
    std::vector<uint8_t> seen;
    explicit TraceChecker(int first):task(first-1) {
        constexpr int stage_counts[14]={6336,6336,6336,9801,9801,6336,6336,6336,6336,25344,25344,6336,6336,6336};
        for(int i=0;i<14;++i) { offsets[i]=per_layer; per_layer+=stage_counts[i]; }
    }
    void finish() {
        if(!started) return;
        if(received!=expected.size()) throw std::runtime_error("Missing CPU-driven encoder intermediate values");
        for(auto value:seen) if(value!=1) throw std::runtime_error("Missing/duplicate intermediate");
        char path[150]; std::snprintf(path,sizeof(path),"build/encoder_cpu/results/task_%02d_trace.bin",task);
        std::ofstream stream(path,std::ios::binary); if(!stream) throw std::runtime_error("Cannot save actual encoder trace");
        stream.write(reinterpret_cast<const char*>(actual.data()),actual.size()*sizeof(int64_t));
        std::printf("CPU_ENCODER_TRACE_PASS task=%d count=%llu\n",task,(unsigned long long)received);
    }
    void observe(const Vkwt_encoder_cpu_soc& top,uint64_t cycle) {
        if(!top.trace_valid) return;
        const int current=top.trace_task;
        if(current!=task) {
            if(current!=task+1) throw std::runtime_error("Trace task order mismatch");
            finish(); task=current; received=0; started=true;
            char path[150]; std::snprintf(path,sizeof(path),"build/encoder/vectors/task_%02d_trace.bin",task);
            std::ifstream stream(path,std::ios::binary|std::ios::ate);
            if(!stream || size_t(stream.tellg())!=12*per_layer*sizeof(int64_t)) throw std::runtime_error("Host-only reference trace size mismatch");
            expected.resize(12*per_layer); actual.assign(expected.size(),0); seen.assign(expected.size(),0);
            stream.seekg(0); stream.read(reinterpret_cast<char*>(expected.data()),expected.size()*sizeof(int64_t));
        }
        constexpr int stage_counts[14]={6336,6336,6336,9801,9801,6336,6336,6336,6336,25344,25344,6336,6336,6336};
        const int layer=top.trace_layer,stage=top.trace_stage,index=top.trace_index;
        if(layer>=12||stage>=14||index>=stage_counts[stage]) throw std::runtime_error("Invalid trace index");
        const size_t pos=layer*per_layer+offsets[stage]+index;
        const int64_t value=static_cast<int64_t>(top.trace_data);
        if(seen[pos]||value!=expected[pos]) {
            std::fprintf(stderr,"CPU_ENCODER_TRACE_FAIL task=%d layer=%d stage=%d index=%d got=%lld expected=%lld cycle=%llu\n",
                         task,layer,stage,index,(long long)value,(long long)expected[pos],(unsigned long long)cycle);
            throw std::runtime_error("CPU-driven RTL differs from frozen integer reference");
        }
        actual[pos]=value; seen[pos]=1; ++received;
    }
};
int main(int argc,char** argv) {
    std::setvbuf(stdout,nullptr,_IONBF,0);
    try {
        auto context=std::make_unique<VerilatedContext>(); context->commandArgs(argc,argv);
        int first=0;
        for(int i=1;i<argc;++i) {
            const std::string arg(argv[i]);
            if(arg.rfind("+FIRST_TASK=",0)==0) first=std::stoi(arg.substr(12));
        }
        auto top=std::make_unique<Vkwt_encoder_cpu_soc>(context.get()); TraceChecker checker(first);
        top->clk=0; top->rst_n=0;
        uint64_t cycle=0;
        for(;cycle<3000000000ULL&&!context->gotFinish();++cycle) {
            top->rst_n=(cycle>=32); top->clk=0; top->eval();
            if(top->rst_n) checker.observe(*top,cycle);
            context->timeInc(1); top->clk=1; top->eval(); context->timeInc(1);
            if(top->sim_done) break;
            if(cycle&&cycle%10000000ULL==0) std::printf("CPU_ENCODER progress cycle=%llu pc=%08x\n",(unsigned long long)cycle,top->inspect_pc);
        }
        top->final();
        if(!top->sim_done||!top->sim_pass) throw std::runtime_error("Real CPU encoder failed or timed out");
        checker.finish();
        std::printf("PASS real E203 full encoder firmware total_cycles=%llu\n",(unsigned long long)cycle);
    } catch(const std::exception& error) { std::fprintf(stderr,"FAIL %s\n",error.what()); return 1; }
    return 0;
}
