#define main residual_fixture_main
#include "../ffn_residual/sim_unified.cpp"
#undef main

int main(int argc,char** argv) {
    try {
        const std::string scenario=argc>1?argv[1]:"actual12";
        Runner runner(argc>2?argv[2]:"models/kwt_unified_optimized_v1",
                      argc>3?argv[3]:"build/optimization/quantization/Q2_training_range",
                      scenario!="single");
        runner.mixed_output=scenario=="mixed_paused";
        runner.response_stall=runner.mixed_output;
        runner.stall_output=runner.mixed_output;
        for(int layer=0;layer<12;++layer)runner.run_linear(layer);
        std::puts("POST_DMA_COMPUTE_ALL_PASS");
        return 0;
    } catch(const std::exception& error) {
        std::fprintf(stderr,"%s\n",error.what());
        return 1;
    }
}
