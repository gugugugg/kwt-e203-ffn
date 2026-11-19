#include "Vkwt_icb_encoder.h"
#include "verilated.h"
#include <cstdint>
#include <algorithm>
#include <cstdio>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

template<class T> std::vector<T> binary(const std::string& path) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f) throw std::runtime_error("Cannot open "+path);
    size_t bytes=size_t(f.tellg());
    std::vector<T> result(bytes/sizeof(T));f.seekg(0);
    f.read(reinterpret_cast<char*>(result.data()),bytes);
    return result;
}
struct Runner {
    VerilatedContext context;
    Vkwt_icb_encoder top{&context};
    uint64_t cycles=0,trace_words=0;
    bool active=false,linear=false;
    std::string package,linear_vectors;
    bool packed_output=false;
    bool stall_output=false;
    bool mixed_output=false,response_stall=false;
    std::vector<int64_t> trace;
    std::vector<unsigned char> seen;
    size_t offsets[14]{};
    size_t per_layer=0;
    static constexpr int counts[14]={6336,6336,6336,9801,9801,6336,6336,6336,6336,25344,25344,6336,6336,6336};
    Runner(std::string pkg="models/kwt_unified_v1",std::string vec="build/unified/vectors",bool packed=false)
        :package(pkg),linear_vectors(vec),packed_output(packed) {
        top.clk=0;top.rst_n=0;top.icb_cmd_valid=0;top.icb_rsp_ready=0;top.icb_cmd_wmask=15;
        for(int i=0;i<14;++i){offsets[i]=per_layer;per_layer+=counts[i];}
        for(int i=0;i<8;++i)step();
        top.rst_n=1;
    }
    void settle(){top.clk=0;top.eval();}
    void step(){
        settle();
        if(active&&top.trace_valid){
            size_t position;
            if(linear){
                if(top.trace_layer!=0||top.trace_stage!=9)throw std::runtime_error("Linear mode executed an unexpected stage");
                position=top.trace_index;
                if(position!=trace_words)throw std::runtime_error("FFN trace is not row-major");
            }else{
                position=size_t(top.trace_layer)*per_layer+offsets[top.trace_stage]+top.trace_index;
            }
            int64_t value=static_cast<int64_t>(top.trace_data);
            if(position>=trace.size()||seen[position]||value!=trace[position]){
                std::fprintf(stderr,"TRACE_FAIL linear=%d layer=%u stage=%u index=%u got=%lld cycle=%llu\n",
                    linear,top.trace_layer,top.trace_stage,top.trace_index,(long long)value,(unsigned long long)cycles);
                throw std::runtime_error("Unified RTL intermediate mismatch");
            }
            seen[position]=1;++trace_words;
        }
        top.clk=1;top.eval();context.timeInc(1);++cycles;
        if(cycles%10000000==0){std::printf("UNIFIED_RTL_PROGRESS cycles=%llu traces=%llu\n",(unsigned long long)cycles,(unsigned long long)trace_words);std::fflush(stdout);}
    }
    uint32_t access(unsigned addr,bool read,uint32_t data=0){
        top.icb_cmd_addr=addr;top.icb_cmd_read=read;top.icb_cmd_wdata=data;top.icb_cmd_valid=1;
        settle();while(!top.icb_cmd_ready)step();
        step();top.icb_cmd_valid=0;settle();
        while(!top.icb_rsp_valid)step();
        uint32_t result=top.icb_rsp_rdata;
        if(top.icb_rsp_err)throw std::runtime_error("ICB error at register "+std::to_string(addr));
        if(response_stall&&read&&(addr==32||addr==52)) for(int n=0;n<4;++n) {
            step();settle();
            if(!top.icb_rsp_valid||top.icb_rsp_rdata!=result||top.icb_rsp_err)
                throw std::runtime_error("Output response changed while CPU was waiting");
        }
        top.icb_rsp_ready=1;step();top.icb_rsp_ready=0;settle();
        return result;
    }
    void wr(unsigned addr,uint32_t data){access(addr,false,data);}
    uint32_t rd(unsigned addr){return access(addr,true);}
    void load(unsigned kind,const std::vector<uint16_t>& values){
        wr(8,kind);wr(12,0);
        for(size_t i=0;i<values.size();) {
            if(mixed_output&&(i%17==0||i+1==values.size())) {wr(16,values[i]);++i;}
            else {wr(48,uint32_t(values[i])|(uint32_t(values[i+1])<<16));i+=2;}
        }
    }
    void begin(bool mode,const std::vector<int64_t>& expected){
        linear=mode;trace=expected;seen.assign(trace.size(),0);trace_words=0;active=true;
        wr(0,2);while(!(rd(4)&8)){}
        wr(44,mode?(RESIDUAL_STREAM?3:1):0);
        if(rd(44)!=(mode?(RESIDUAL_STREAM?3u:1u):0u))throw std::runtime_error("Mode readback mismatch");
    }
    void receive_range(const std::vector<int16_t>& expected,size_t first,size_t end){
        for(size_t i=first;i<end;){
            bool pair=packed_output&&(!mixed_output||(i%17!=0))&&i+1<end;
            if(!(rd(36)&2)||rd(28)!=i)throw std::runtime_error("Output index mismatch");
            uint32_t word=rd(pair?52:32);
            int16_t value=int16_t(word);
            if(value!=expected[i]){
                std::fprintf(stderr,"OUTPUT_FAIL index=%zu got=%d expected=%d\n",i,value,expected[i]);
                throw std::runtime_error("Unified RTL output mismatch");
            }
            if(pair&&int16_t(word>>16)!=expected[i+1])throw std::runtime_error("Packed high output mismatch");
            i+=pair?2:1;
        }
    }
    void finish(){
        while(!(rd(4)&64)){}
        if(trace_words!=trace.size())throw std::runtime_error("Incomplete stage trace");
        active=false;
    }
    void receive(const std::vector<int16_t>& expected){receive_range(expected,0,expected.size());finish();}
    void run_linear(int layer){
        char name[160];
        std::snprintf(name,sizeof(name),"%s/linear_%02d_expected.bin",linear_vectors.c_str(),layer);
        auto expected=binary<int16_t>(name);
        std::vector<int64_t> values(expected.begin(),expected.end());
        uint64_t start=cycles;begin(true,values);
        std::snprintf(name,sizeof(name),"%s/linear_%02d_input.bin",linear_vectors.c_str(),layer);
        auto inputs=binary<uint16_t>(name);
        if(!RESIDUAL_STREAM)load(0,inputs);
        wr(0,1);if(!(rd(36)&16))throw std::runtime_error("Missing linear parameter request");
        std::snprintf(name,sizeof(name),"%s/linear/layer_%02d_parameters.bin",package.c_str(),layer);load(1,binary<uint16_t>(name));
        std::snprintf(name,sizeof(name),"%s/linear/layer_%02d_shifts.bin",package.c_str(),layer);load(5,binary<uint16_t>(name));
        if(!(rd(4)&32))throw std::runtime_error("Linear parameters incomplete");
        if(RESIDUAL_STREAM){wr(8,0);wr(12,0);}
        wr(24,1);
        if(RESIDUAL_STREAM){
            auto upload=[&](size_t row){
                size_t end=std::min(size_t(99),row+RESIDUAL_ROW_GROUP)*64;
                for(size_t j=row*64;j<end;){
                    if(mixed_output&&(j%17==0||j+1==end)){wr(16,inputs[j]);++j;}
                    else{wr(48,uint32_t(inputs[j])|(uint32_t(inputs[j+1])<<16));j+=2;}
                }
            };
            if(RESIDUAL_DOUBLE_BUFFER)upload(0);
            for(size_t row=0;row<99;row+=RESIDUAL_ROW_GROUP){
                if(!RESIDUAL_DOUBLE_BUFFER)upload(row);
                else if(row+RESIDUAL_ROW_GROUP<99)upload(row+RESIDUAL_ROW_GROUP);
                if(stall_output&&layer==0&&row==0)for(int pause=0;pause<4096;++pause)step();
                receive_range(expected,row*256,std::min(size_t(99),row+RESIDUAL_ROW_GROUP)*256);
            }
            finish();
        }else{
            if(stall_output&&layer==0)for(int pause=0;pause<4096;++pause)step();
            receive(expected);
        }
        std::printf("UNIFIED_LINEAR_PASS layer=%d outputs=%zu trace=%llu bus_cycles=%llu\n",layer,expected.size(),(unsigned long long)trace_words,(unsigned long long)(cycles-start));std::fflush(stdout);
    }
    void run_encoder(int task){
        char name[160];
        std::snprintf(name,sizeof(name),"build/encoder/vectors/task_%02d_trace.bin",task);
        uint64_t start=cycles;begin(false,binary<int64_t>(name));
        std::snprintf(name,sizeof(name),"build/encoder/vectors/task_%02d_input.bin",task);load(0,binary<uint16_t>(name));
        load(3,binary<uint16_t>("build/encoder/vectors/exp.bin"));load(4,binary<uint16_t>("build/encoder/vectors/gelu.bin"));
        auto configs=binary<uint16_t>(package+"/encoder_configs.bin");
        wr(0,1);
        for(int layer=0;layer<12;++layer){
            if(!(rd(36)&16)||rd(20)!=unsigned(layer))throw std::runtime_error("Encoder layer request mismatch");
            std::snprintf(name,sizeof(name),"models/kwt1_fixed16_v1/layer_%02d.bin",layer);load(1,binary<uint16_t>(name));
            load(2,std::vector<uint16_t>(configs.begin()+layer*32,configs.begin()+(layer+1)*32));
            if(!(rd(4)&32))throw std::runtime_error("Encoder parameters incomplete");
            wr(24,1);
        }
        std::snprintf(name,sizeof(name),"build/encoder/vectors/task_%02d_expected.bin",task);
        auto expected=binary<int16_t>(name);receive(expected);
        std::printf("UNIFIED_ENCODER_PASS task=%d outputs=%zu trace=%llu bus_cycles=%llu\n",task,expected.size(),(unsigned long long)trace_words,(unsigned long long)(cycles-start));std::fflush(stdout);
    }
};
int main(int argc,char**argv){
    try{
        Runner runner(argc>2?argv[2]:"models/kwt_unified_v1",argc>3?argv[3]:"build/unified/vectors",
                      argc>4&&std::string(argv[4])=="packed");
        runner.stall_output=argc>1&&std::string(argv[1])=="linear-stall";
        runner.mixed_output=argc>1&&std::string(argv[1])=="linear-mixed";
        runner.response_stall=runner.mixed_output;
        if(argc>1&&(std::string(argv[1])=="linear"||runner.stall_output||runner.mixed_output)){
            for(int i=0;i<12;++i)runner.run_linear(i);
        }else{
            runner.run_encoder(0);
            for(int i=0;i<12;++i)runner.run_linear(i);
            runner.run_encoder(1);
        }
        std::puts("UNIFIED_RTL_ALL_PASS");return 0;
    }catch(const std::exception&e){std::fprintf(stderr,"%s\n",e.what());return 1;}
}
