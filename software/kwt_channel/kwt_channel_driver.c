#include "kwt_channel_driver.h"
#ifndef KWT_FAST_IO
#define KWT_FAST_IO 1
#endif
enum { CTRL=0, SHIFT=4, KIND=8, ADDR=12, DATA=16, INDEX=20, OUT=24, STATE=28 };
static uint32_t rd(const kwt_device *d, unsigned off) {
    return *(volatile uint32_t *)(d->base+off);
}
static void wr(const kwt_device *d,unsigned off,uint32_t value) {
    *(volatile uint32_t *)(d->base+off)=value;
}
static void fence_io(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static int wait_mask(const kwt_device *d,unsigned reg,uint32_t mask) {
    for(uint32_t n=0;n<d->poll_limit;++n) {
        if(rd(d,CTRL)&4u) return KWT_HW_ERROR;
        if(rd(d,reg)&mask) return KWT_OK;
    }
    return KWT_TIMEOUT;
}
static void load_words(const kwt_device *d,unsigned kind,const uint16_t *words,size_t count) {
    wr(d,KIND,kind); wr(d,ADDR,0);
#if KWT_FAST_IO
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
#else
    const volatile uint16_t *source=words;
    for(size_t i=0;i<count;++i) wr(d,DATA,source[i]);
#endif
    fence_io();
}
int kwt_ffn_channel_run(const kwt_device *d,const int16_t input[99*64],
                        const int16_t kernel[64*256],const int64_t bias[256],
                        const uint16_t shift_words[128],int8_t legacy_shift,int16_t output[99*256]) {
    int status=wait_mask(d,STATE,8u);
    if(status) return status;
    wr(d,SHIFT,(uint32_t)(int32_t)legacy_shift);
    load_words(d,0,(const uint16_t *)input,6336);
    load_words(d,1,(const uint16_t *)kernel,16384);
    wr(d,KIND,2); wr(d,ADDR,0);
    for(size_t i=0;i<256;++i) {
        uint64_t bits=(uint64_t)bias[i];
        for(unsigned word=0;word<4;++word) wr(d,DATA,(uint16_t)(bits>>(16u*word)));
    }
    load_words(d,3,shift_words,128);
    fence_io(); wr(d,CTRL,1); fence_io();
    for(size_t i=0;i<99u*256u;++i) {
#if KWT_FAST_IO
        if((i&7u)==0 && (rd(d,CTRL)&4u)) return KWT_HW_ERROR;
#else
        status=wait_mask(d,STATE,2u);
        if(status) return status;
        if(rd(d,INDEX)!=(uint32_t)i) return KWT_HW_ERROR;
#endif
        output[i]=(int16_t)rd(d,OUT);
    }
    fence_io();
    status=wait_mask(d,CTRL,2u);
    if(status) return status;
    return (rd(d,CTRL)&4u)?KWT_HW_ERROR:KWT_OK;
}
