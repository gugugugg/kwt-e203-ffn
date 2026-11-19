#include "kwt_unified_driver.h"
enum { CTRL=0,STATE=4,KIND=8,ADDR=12,DATA=16,LAYER=20,START_LAYER=24,
       INDEX=28,OUT=32,EVENT=36,ID=40,MODE=44,PACKED_DATA=48,PACKED_OUT=52 };
static uint32_t rd(const kwu_device *d,unsigned off) { return *(volatile uint32_t *)(d->base+off); }
static void wr(const kwu_device *d,unsigned off,uint32_t value) { *(volatile uint32_t *)(d->base+off)=value; }
static void fence_io(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static int wait_state(const kwu_device *d,uint32_t mask) {
    for(;;) {
        uint32_t s=rd(d,STATE);
        if(s&128u) return KWU_HW_ERROR;
        if(s&mask) return KWU_OK;
    }
}
static void load32(const kwu_device *d,unsigned kind,const uint32_t *words,size_t count) {
    wr(d,KIND,kind); wr(d,ADDR,0);
    for(size_t i=0;i<count;++i) {
#ifdef KWU_UNPACKED_LOAD
        uint32_t value=words[i];
        wr(d,DATA,value);wr(d,DATA,value>>16);
#else
        wr(d,PACKED_DATA,words[i]);
#endif
    }
    fence_io();
}
#if defined(KWU_FFN_UNROLL) || defined(KWU_BATCH_LOAD) || defined(KWU_BATCH_OUTPUT)
static void load32_ffn(const kwu_device *d,unsigned kind,const uint32_t *words,size_t count) {
    wr(d,KIND,kind); wr(d,ADDR,0);
    size_t i=0;
#ifdef KWU_BATCH_LOAD
    for(;i+4<=count;i+=4) {
        uint32_t a=words[i],b=words[i+1],c=words[i+2],e=words[i+3];
        wr(d,PACKED_DATA,a);wr(d,PACKED_DATA,b);wr(d,PACKED_DATA,c);wr(d,PACKED_DATA,e);
    }
#elif defined(KWU_FFN_UNROLL)
    for(;i+8<=count;i+=8) {
        wr(d,PACKED_DATA,words[i]); wr(d,PACKED_DATA,words[i+1]);
        wr(d,PACKED_DATA,words[i+2]); wr(d,PACKED_DATA,words[i+3]);
        wr(d,PACKED_DATA,words[i+4]); wr(d,PACKED_DATA,words[i+5]);
        wr(d,PACKED_DATA,words[i+6]); wr(d,PACKED_DATA,words[i+7]);
    }
#endif
    for(;i<count;++i) wr(d,PACKED_DATA,words[i]);
    fence_io();
}

#else
#define load32_ffn load32
#endif
static int begin(const kwu_device *d,unsigned mode) {
    if(rd(d,ID)!=0x4b574531u) return KWU_HW_ERROR;
    wr(d,CTRL,2); fence_io();
    int rc=wait_state(d,8u); if(rc) return rc;
    wr(d,MODE,mode); fence_io();
    return KWU_OK;
}
static int receive(const kwu_device *d,int16_t *output,size_t count) {
    uint32_t s=rd(d,EVENT);
    if((s&128u)||!(s&2u)) return KWU_HW_ERROR;
#ifdef KWU_PACKED_OUTPUT
    typedef uint32_t packed_word __attribute__((may_alias));
    packed_word *pairs=(packed_word *)(void *)output;
    for(size_t i=0;i<count/2;++i) pairs[i]=rd(d,PACKED_OUT);
#else
    for(size_t i=0;i<count;++i) {
        output[i]=(int16_t)rd(d,OUT);
    }
#endif
    fence_io();
    return wait_state(d,64u);
}
int kwu_run_encoder(const kwu_device *d,const uint32_t input[3168],
                    const uint32_t exp_table[4097],const uint32_t gelu_table[4097],
                    kwu_stage_layer stage,void *context,int16_t output[6336]) {
    int rc=begin(d,KWU_ENCODER); if(rc) return rc;
    load32(d,0,input,3168); load32(d,3,exp_table,4097); load32(d,4,gelu_table,4097);
    wr(d,CTRL,1); fence_io();
    for(unsigned layer=0;layer<12;++layer) {
        uint32_t s=rd(d,EVENT);
        if((s&128u)||!(s&16u)||rd(d,LAYER)!=layer) return KWU_HW_ERROR;
        const uint32_t *parameters,*config;
        rc=stage(context,layer,&parameters,&config); if(rc) return rc;
        load32(d,1,parameters,25856); load32(d,2,config,16);
        rc=wait_state(d,32u); if(rc) return rc;
        wr(d,START_LAYER,1); fence_io();
    }
    return receive(d,output,6336);
}
static void stream_input(const kwu_device *d,const uint32_t *words,size_t count) {
    size_t i=0;
#ifdef KWU_BATCH_LOAD
    for(;i+4<=count;i+=4) {
        uint32_t a=words[i],b=words[i+1],c=words[i+2],e=words[i+3];
        wr(d,PACKED_DATA,a);wr(d,PACKED_DATA,b);wr(d,PACKED_DATA,c);wr(d,PACKED_DATA,e);
    }
#elif defined(KWU_FFN_UNROLL)
    for(;i+8<=count;i+=8)for(unsigned j=0;j<8;++j)wr(d,PACKED_DATA,words[i+j]);
#endif
    for(;i<count;++i)wr(d,PACKED_DATA,words[i]);
    fence_io();
}
static void stream_output(const kwu_device *d,int16_t *output,size_t count) {
    typedef uint32_t packed_word __attribute__((may_alias));
    packed_word *pairs=(packed_word *)(void *)output;
    size_t i=0,n=count/2;
#ifdef KWU_BATCH_OUTPUT
    for(;i+4<=n;i+=4) {
        uint32_t a=rd(d,PACKED_OUT),b=rd(d,PACKED_OUT),c=rd(d,PACKED_OUT),e=rd(d,PACKED_OUT);
        pairs[i]=a;pairs[i+1]=b;pairs[i+2]=c;pairs[i+3]=e;
    }
#elif defined(KWU_FFN_UNROLL)
    for(;i+8<=n;i+=8)for(unsigned j=0;j<8;++j)pairs[i+j]=rd(d,PACKED_OUT);
#endif
    for(;i<n;++i)pairs[i]=rd(d,PACKED_OUT);
    fence_io();
}
int kwu_run_linear(const kwu_device *d,const uint32_t input[3168],
                   kwu_stage_layer stage,void *context,int16_t output[25344]) {
    int rc=begin(d,3); if(rc)return rc;
    wr(d,CTRL,1);fence_io();
    uint32_t s=rd(d,EVENT);
    if((s&128u)||!(s&16u)||rd(d,LAYER)!=0)return KWU_HW_ERROR;
    const uint32_t *parameters,*shifts;
    rc=stage(context,0,&parameters,&shifts);if(rc)return rc;
    load32_ffn(d,1,parameters,8704);load32_ffn(d,5,shifts,64);
    rc=wait_state(d,32u);if(rc)return rc;
    wr(d,KIND,0);wr(d,ADDR,0);wr(d,START_LAYER,1);fence_io();
#ifdef KWU_DOUBLE_BUFFER
    stream_input(d,input,KWU_ROW_GROUP*32u);
#endif
    for(unsigned row=0;row<99;row+=KWU_ROW_GROUP) {
        unsigned rows=(99-row<KWU_ROW_GROUP)?99-row:KWU_ROW_GROUP;
#ifdef KWU_DOUBLE_BUFFER
        unsigned next=row+KWU_ROW_GROUP;
        if(next<99) {
            unsigned next_rows=(99-next<KWU_ROW_GROUP)?99-next:KWU_ROW_GROUP;
            stream_input(d,input+next*32u,next_rows*32u);
        }
#else
        stream_input(d,input+row*32u,rows*32u);
#endif
        stream_output(d,output+row*256u,rows*256u);
    }
    return wait_state(d,64u);
}
