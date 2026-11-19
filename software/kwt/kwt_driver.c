#include "kwt_driver.h"
enum { CTRL=0, SHIFT=4, KIND=8, ADDR=12, DATA=16, INDEX=20, OUT=24, STATE=28 };
static uint32_t rd(const kwt_device *d, unsigned offset) {
    return *(volatile uint32_t *)(d->base+offset);
}
static void wr(const kwt_device *d, unsigned offset, uint32_t value) {
    *(volatile uint32_t *)(d->base+offset)=value;
}
static void fence_io(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static int wait_mask(const kwt_device *d, unsigned reg, uint32_t mask) {
    for(uint32_t n=0; n<d->poll_limit; ++n) {
        if(rd(d,CTRL)&4u) return KWT_HW_ERROR;
        if(rd(d,reg)&mask) return KWT_OK;
    }
    return KWT_TIMEOUT;
}
static void select_load(const kwt_device *d, uint32_t kind) {
    wr(d,KIND,kind); wr(d,ADDR,0);
}
int kwt_ffn_run(const kwt_device *d,const int16_t input[99*64],const int16_t kernel[64*256],
                const int64_t bias[256],int8_t shift,int16_t output[99*256]) {
    if(!d || !input || !kernel || !bias || !output || !d->poll_limit ||
       (d->base&3u) || shift < -30 || shift > 62) return KWT_BAD_ARGUMENT;
    int status=wait_mask(d,STATE,8u);
    if(status) return status;
    wr(d,SHIFT,(uint32_t)(int32_t)shift);
    select_load(d,0);
    for(size_t i=0;i<99u*64u;++i) wr(d,DATA,(uint16_t)input[i]);
    select_load(d,1);
    for(size_t i=0;i<64u*256u;++i) wr(d,DATA,(uint16_t)kernel[i]);
    select_load(d,2);
    for(size_t i=0;i<256u;++i) {
        uint64_t bits=(uint64_t)bias[i];
        for(unsigned word=0;word<4;++word) wr(d,DATA,(uint16_t)(bits>>(16u*word)));
    }
    fence_io(); wr(d,CTRL,1); fence_io();
    for(size_t i=0;i<99u*256u;++i) {
        status=wait_mask(d,STATE,2u);
        if(status) return status;
        if(rd(d,INDEX)!=(uint32_t)i) return KWT_HW_ERROR;
        output[i]=(int16_t)rd(d,OUT);
    }
    fence_io();
    status=wait_mask(d,CTRL,2u);
    if(status) return status;
    return (rd(d,CTRL)&4u) ? KWT_HW_ERROR : KWT_OK;
}
