/* Same encoder ABI and arithmetic; only shared-SRAM reads and loop scheduling change. */
#include "kwt_encoder_driver.h"
enum { CTRL=0,STATE=4,KIND=8,ADDR=12,DATA=16,LAYER=20,START_LAYER=24,INDEX=28,OUT=32,EVENT=36,ID=40 };
static uint32_t rd(const kwe_device *d,unsigned off) { return *(volatile uint32_t *)(d->base+off); }
static void wr(const kwe_device *d,unsigned off,uint32_t value) { *(volatile uint32_t *)(d->base+off)=value; }
static void fence_io(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static int wait_ready(const kwe_device *d,uint32_t mask) {
    for(uint32_t i=0;i<d->poll_limit;++i) {
        uint32_t s=rd(d,STATE);
        if(s&128u) return KWE_HW_ERROR;
        if(s&mask) return KWE_OK;
    }
    return KWE_TIMEOUT;
}
/* Sources are memory-mapped shared SRAM. Use volatile accesses, check alignment,
   and keep a scalar tail. Both halfwords still cross the original DATA port.
   No extra SRAM, DMA, cached layer or numerical operation is introduced. */
static void load(const kwe_device *d,unsigned kind,const uint16_t *words,size_t count) {
    wr(d,KIND,kind); wr(d,ADDR,0);
#if !defined(KWE_SCALAR_UNROLL)
    if(((uintptr_t)words&3u)==0) {
        const volatile uint32_t *pairs=(const volatile uint32_t *)(uintptr_t)words;
        size_t n=count/2,i=0;
        for(;i+4<=n;i+=4) {
            uint32_t a=pairs[i],b=pairs[i+1],c=pairs[i+2],e=pairs[i+3];
            wr(d,DATA,a&65535u); wr(d,DATA,a>>16);
            wr(d,DATA,b&65535u); wr(d,DATA,b>>16);
            wr(d,DATA,c&65535u); wr(d,DATA,c>>16);
            wr(d,DATA,e&65535u); wr(d,DATA,e>>16);
        }
        for(;i<n;++i) { uint32_t a=pairs[i]; wr(d,DATA,a&65535u); wr(d,DATA,a>>16); }
        if(count&1u) wr(d,DATA,((const volatile uint16_t *)words)[count-1]);
        fence_io(); return;
    }
#endif
    size_t i=0;
    const volatile uint16_t *source=words;
    for(;i+8<=count;i+=8) {
        wr(d,DATA,source[i]); wr(d,DATA,source[i+1]);
        wr(d,DATA,source[i+2]); wr(d,DATA,source[i+3]);
        wr(d,DATA,source[i+4]); wr(d,DATA,source[i+5]);
        wr(d,DATA,source[i+6]); wr(d,DATA,source[i+7]);
    }
    for(;i<count;++i) wr(d,DATA,source[i]);
    fence_io();
}
int kwe_run(const kwe_device *d,const int16_t input[6336],
            const uint16_t exp_words[8194],const uint16_t gelu_words[8194],
            kwe_stage_layer stage_layer,void *context,int16_t output[6336]) {
    if(!d||!input||!exp_words||!gelu_words||!stage_layer||!output||!d->poll_limit||(d->base&3u)) return KWE_BAD_ARGUMENT;
    if(rd(d,ID)!=0x4b574531u) return KWE_HW_ERROR;
    wr(d,CTRL,2); fence_io();
    int rc=wait_ready(d,8u); if(rc) return rc;
    load(d,0,(const uint16_t *)input,6336); load(d,3,exp_words,8194); load(d,4,gelu_words,8194);
    wr(d,CTRL,1); fence_io();
    for(unsigned layer=0;layer<12;++layer) {
        uint32_t s=rd(d,EVENT);
        if((s&128u)||!(s&16u)||rd(d,LAYER)!=layer) return KWE_HW_ERROR;
        const uint16_t *parameters=0,*config=0;
        rc=stage_layer(context,layer,&parameters,&config);
        if(rc) return rc;
        if(!parameters||!config) return KWE_BAD_ARGUMENT;
        load(d,1,parameters,51712); load(d,2,config,32);
        s=rd(d,STATE); if((s&128u)||!(s&32u)) return KWE_HW_ERROR;
        wr(d,START_LAYER,1); fence_io();
    }
    uint32_t s=rd(d,EVENT);
    if((s&128u)||!(s&2u)) return KWE_HW_ERROR;
    for(size_t i=0;i<6336;++i) {
        if(rd(d,INDEX)!=i) return KWE_HW_ERROR;
        output[i]=(int16_t)rd(d,OUT);
    }
    fence_io(); rc=wait_ready(d,64u);
    return rc?rc:((rd(d,STATE)&128u)?KWE_HW_ERROR:KWE_OK);
}
