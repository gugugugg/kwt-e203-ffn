#include "Vkwt_ffn_quantizer_check.h"
#include "verilated.h"
#include <fstream>
#include <cstdint>
#include <cstdio>
int main(int argc,char**argv){
    VerilatedContext context;
    Vkwt_ffn_quantizer_check top{&context};
    std::ifstream vectors(argv[1]);
    int64_t value;int shift,expected;unsigned count=0;
    while(vectors>>value>>shift>>expected){
        top.value=uint64_t(value);top.shift=shift;top.eval();
        if(int16_t(top.generic_result)!=expected||int16_t(top.special_result)!=expected){
            std::fprintf(stderr,"QUANT_FAIL value=%lld shift=%d expected=%d generic=%d special=%d\n",
                (long long)value,shift,expected,int16_t(top.generic_result),int16_t(top.special_result));return 1;
        }
        ++count;
    }
    std::printf("QUANTIZER_GOLDEN_PASS cases=%u\n",count);
    return count?0:1;
}
