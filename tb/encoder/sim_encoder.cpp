#include "Vkwt_encoder.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

template<class T> std::vector<T> read_binary(const std::string& path) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f) throw std::runtime_error("Cannot open "+path);
    const auto n=f.tellg();
    if(n<0 || size_t(n)%sizeof(T)) throw std::runtime_error("Bad binary size "+path);
    std::vector<T> v(size_t(n)/sizeof(T)); f.seekg(0);
    f.read(reinterpret_cast<char*>(v.data()),n); return v;
}
template<class T> void write_binary(const std::string& path,const std::vector<T>& v) {
    std::ofstream f(path,std::ios::binary); if(!f) throw std::runtime_error("Cannot write "+path);
    f.write(reinterpret_cast<const char*>(v.data()),v.size()*sizeof(T));
}
static constexpr int counts[14]={6336,6336,6336,9801,9801,6336,6336,6336,6336,25344,25344,6336,6336,6336};
struct Runner {
    std::unique_ptr<VerilatedContext> context=std::make_unique<VerilatedContext>();
    Vkwt_encoder top{context.get()};
    uint64_t cycles=0,task_start=0,load_words=0,trace_words=0;
    bool active=false,stalled=false;
    uint16_t held_data=0,held_index=0;
    size_t per_layer=0;
    size_t offsets[14]{};
    int task=0,next_layer=0;
    std::vector<int64_t> expected,actual;
    std::vector<uint8_t> seen;
    std::vector<int16_t> output;
    Runner() {
        for(int i=0;i<14;++i) { offsets[i]=per_layer; per_layer+=counts[i]; }
        top.rst_n=0; top.clk=0; top.load_valid=0; top.start_valid=0; top.layer_start_valid=0; top.out_ready=0;
    }
    void settle() { top.clk=0; top.eval(); }
    void step() {
        top.out_ready=(cycles%7!=0 && cycles%11!=0); settle();
        if(active && top.trace_valid) {
            int l=top.trace_layer,s=top.trace_stage,i=top.trace_index;
            if(l>=12||s>=14||i>=counts[s]) throw std::runtime_error("Invalid trace index");
            const size_t pos=l*per_layer+offsets[s]+i;
            const int64_t value=static_cast<int64_t>(top.trace_data);
            if(seen[pos] || value!=expected[pos]) {
                std::fprintf(stderr,"TRACE_FAIL task=%d layer=%d stage=%d index=%d got=%lld expected=%lld seen=%d cycle=%llu\n",
                    task,l,s,i,(long long)value,(long long)expected[pos],seen[pos],(unsigned long long)cycles);
                throw std::runtime_error("RTL intermediate mismatch");
            }
            seen[pos]=1; actual[pos]=value; ++trace_words;
        }
        if(active) {
            if(stalled && (!top.out_valid || top.out_data!=held_data || top.out_index!=held_index))
                throw std::runtime_error("Output changed under backpressure");
            stalled=top.out_valid&&!top.out_ready;
            held_data=top.out_data; held_index=top.out_index;
            if(top.out_valid&&top.out_ready) {
                if(top.out_index!=output.size()) throw std::runtime_error("Bad output order");
                output.push_back(static_cast<int16_t>(top.out_data));
            }
        }
        top.clk=1; top.eval(); context->timeInc(10); ++cycles;
        if(active && top.error) throw std::runtime_error("Encoder reports an error");
        if(cycles>3000000000ULL) throw std::runtime_error("Encoder timeout");
    }
    void load(unsigned kind,const std::vector<uint16_t>& words) {
        top.load_kind=kind; top.load_valid=1;
        for(size_t i=0;i<words.size();++i) {
            top.load_addr=i; top.load_data=words[i]; settle();
            if(!top.load_ready) throw std::runtime_error("Load not ready");
            step(); ++load_words;
            if(i%997==996) { top.load_valid=0; step(); top.load_valid=1; }
        }
        top.load_valid=0; settle();
    }
    void run(int id,const std::vector<uint16_t>& exp,const std::vector<uint16_t>& gelu,
             const std::vector<uint16_t>& configs,const std::vector<std::vector<uint16_t>>& params,
             const std::string& result_dir) {
        char p[200]; task=id; next_layer=0; output.clear(); stalled=false; trace_words=0; load_words=0;
        std::snprintf(p,sizeof(p),"build/encoder/vectors/task_%02d_trace.bin",id);
        expected=read_binary<int64_t>(p); actual.assign(expected.size(),0); seen.assign(expected.size(),0);
        if(expected.size()!=12*per_layer) throw std::runtime_error("Trace shape mismatch");
        while(!top.start_ready) step();
        task_start=cycles; active=true;
        std::snprintf(p,sizeof(p),"build/encoder/vectors/task_%02d_input.bin",id);
        load(0,read_binary<uint16_t>(p)); load(3,exp); load(4,gelu);
        top.start_valid=1; step(); top.start_valid=0; settle();
        for(;;) {
            if(top.layer_request) {
                const int l=top.layer_index;
                if(l!=next_layer++) throw std::runtime_error("Unexpected parameter request order");
                load(1,params[l]);
                load(2,std::vector<uint16_t>(configs.begin()+l*32,configs.begin()+(l+1)*32));
                settle(); if(!top.layer_start_ready) throw std::runtime_error("Layer not ready after complete load");
                top.layer_start_valid=1; step(); top.layer_start_valid=0; settle();
            }
            step();
            if(top.layer_done) std::printf("ENCODER_LAYER_PASS task=%d completed=%d cycle=%llu\n",id,next_layer,(unsigned long long)(cycles-task_start));
            if(top.done) break;
        }
        active=false;
        if(next_layer!=12||output.size()!=6336||trace_words!=expected.size()) throw std::runtime_error("Incomplete encoder result/trace");
        for(auto v:seen) if(v!=1) throw std::runtime_error("Missing intermediate");
        std::snprintf(p,sizeof(p),"build/encoder/vectors/task_%02d_expected.bin",id);
        if(output!=read_binary<int16_t>(p)) throw std::runtime_error("Final writeback mismatch");
        std::snprintf(p,sizeof(p),"%s/task_%02d_output.bin",result_dir.c_str(),id); write_binary(p,output);
        std::snprintf(p,sizeof(p),"%s/task_%02d_trace.bin",result_dir.c_str(),id); write_binary(p,actual);
        std::printf("ENCODER_TASK_PASS task=%d layers=12 words=6336 trace_words=%llu load_words=%llu cycles=%llu\n",id,
                    (unsigned long long)trace_words,(unsigned long long)load_words,(unsigned long long)(cycles-task_start));
    }
    void preflight(const std::vector<uint16_t>& exp,const std::vector<uint16_t>& gelu,
                   const std::vector<uint16_t>& configs,const std::vector<std::vector<uint16_t>>& params) {
        while(!top.start_ready) step();
        top.start_valid=1; step(); top.start_valid=0;
        if(!top.done||!top.error) throw std::runtime_error("Incomplete start was not rejected");
        top.rst_n=0; for(int i=0;i<4;++i) step(); top.rst_n=1;
        while(!top.start_ready) step();
        // Reject an out-of-order input word without advancing the coverage count.
        top.load_kind=0; top.load_addr=1; top.load_data=0; top.load_valid=1; step(); top.load_valid=0;
        if(!top.error) throw std::runtime_error("Skipped load address was accepted");
        top.rst_n=0; for(int i=0;i<4;++i) step(); top.rst_n=1;
        while(!top.start_ready) step();
        load(0,read_binary<uint16_t>("build/encoder/vectors/task_00_input.bin")); load(3,exp); load(4,gelu);
        top.start_valid=1; step(); top.start_valid=0; settle();
        if(!top.layer_request||top.layer_start_ready) throw std::runtime_error("Layer started without parameters");
        load(1,params[0]); load(2,std::vector<uint16_t>(configs.begin(),configs.begin()+32));
        top.layer_start_valid=1; step(); top.layer_start_valid=0;
        for(int i=0;i<200;++i) step();
        top.rst_n=0; for(int i=0;i<4;++i) step(); top.rst_n=1;
        while(!top.start_ready) step();
        if(top.out_valid||top.layer_request||top.error) throw std::runtime_error("Interrupted task survived reset");
        std::printf("ENCODER_PROTOCOL_PASS incomplete_start skipped_load missing_parameters reset_mid_compute\n");
    }
};
int main(int argc,char** argv) {
    std::setvbuf(stdout,nullptr,_IONBF,0);
    try {
        int tasks=argc>1?std::stoi(argv[1]):14;
        const std::string result_dir=argc>2?argv[2]:"build/encoder/results";
        if(tasks<1||tasks>14) throw std::runtime_error("Tasks must be 1..14");
        auto exp=read_binary<uint16_t>("build/encoder/vectors/exp.bin");
        auto gelu=read_binary<uint16_t>("build/encoder/vectors/gelu.bin");
        auto configs=read_binary<uint16_t>("build/encoder/vectors/configs.bin");
        std::vector<std::vector<uint16_t>> params;
        for(int l=0;l<12;++l) {
            char p[100]; std::snprintf(p,sizeof(p),"models/kwt1_fixed16_v1/layer_%02d.bin",l);
            params.push_back(read_binary<uint16_t>(p));
            if(params.back().size()!=51712) throw std::runtime_error("Layer parameter length mismatch");
        }
        Runner r;
        for(int i=0;i<4;++i) r.step(); r.top.rst_n=1;
        r.preflight(exp,gelu,configs,params);
        for(int task=0;task<tasks;++task) r.run(task,exp,gelu,configs,params,result_dir);
        r.top.final();
        std::printf("ENCODER_ALL_PASS tasks=%d words=%d\n",tasks,tasks*6336);
    } catch(const std::exception& e) { std::fprintf(stderr,"FAIL %s\n",e.what()); return 1; }
    return 0;
}
