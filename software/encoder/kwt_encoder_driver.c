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
static void load(const kwe_device *d,unsigned kind,const uint16_t *words,size_t count) {
    wr(d,KIND,kind); wr(d,ADDR,0);
    for(size_t i=0;i<count;++i) wr(d,DATA,words[i]);
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
        /* A real blocking ICB read lets the CPU wait while RTL computes.
           It unblocks on layer request, available output, completion or error. */
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
