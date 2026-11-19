#include "kwt_unified_driver.h"
enum { CTRL=0,STATE=4,KIND=8,ADDR=12,DATA=16,LAYER=20,START_LAYER=24,
       INDEX=28,OUT=32,EVENT=36,ID=40,MODE=44,PACKED_DATA=48,PACKED_OUT=52 };
static uint32_t rd(const kwu_device *d,unsigned off) { return *(volatile uint32_t *)(d->base+off); }
static void wr(const kwu_device *d,unsigned off,uint32_t value) { *(volatile uint32_t *)(d->base+off)=value; }
static void fence_io(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static void ld_prepare(uintptr_t base,const void *buffer,size_t words) {
    fence_io();
    *(volatile uint32_t *)(base+0x40u)=(uint32_t)(uintptr_t)buffer;
    *(volatile uint32_t *)(base+0x44u)=(uint32_t)words;
}
static void ld_launch(uintptr_t base,unsigned direction) {
    fence_io();*(volatile uint32_t *)(base+0x48u)=direction;fence_io();
}
static int ld_join(uintptr_t base) {
    uint32_t status=*(volatile uint32_t *)(base+0x50u);fence_io();
    return (status&4u)?KWU_HW_ERROR:KWU_OK;
}

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

static uint32_t rd_base(uintptr_t base,unsigned offset){return *(volatile uint32_t *)(base+offset);}
static void wr_base(uintptr_t base,unsigned offset,uint32_t value){*(volatile uint32_t *)(base+offset)=value;}
extern void kwt_transport_load4(uintptr_t,const uint32_t *,size_t);
extern void kwt_transport_output4(uintptr_t,uint32_t *,size_t);


static void transport_output(uintptr_t base,int16_t *output,size_t count) {
 typedef uint32_t packed_word __attribute__((may_alias));
 packed_word *words=(packed_word *)(void *)output;count/=2;
 size_t i=0;
 for(;i+4<=count;i+=4) {
  uint32_t word0=rd_base(base,PACKED_OUT);
  uint32_t word1=rd_base(base,PACKED_OUT);
  uint32_t word2=rd_base(base,PACKED_OUT);
  uint32_t word3=rd_base(base,PACKED_OUT);
  words[i+0]=word0;
  words[i+1]=word1;
  words[i+2]=word2;
  words[i+3]=word3;
 }
 for(;i<count;++i)words[i]=rd_base(base,PACKED_OUT);
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
    uintptr_t base=d->base;
    wr_base(base,KIND,1);wr_base(base,ADDR,0);
    ld_prepare(base,parameters,8704u);
    ld_launch(base,1u);
    ld_prepare(base,shifts,64u);
    rc=ld_join(base);if(rc)return rc;
    wr_base(base,KIND,5);wr_base(base,ADDR,0);
    ld_launch(base,1u);
    ld_prepare(base,input,32u);
    rc=ld_join(base);if(rc)return rc;
    rc=wait_state(d,32u);if(rc)return rc;
    wr(d,KIND,0);wr(d,ADDR,0);wr(d,START_LAYER,1);fence_io();
    ld_launch(base,1u);
    ld_prepare(base,input+32u,32u);
    rc=ld_join(base);if(rc)return rc;
    for(unsigned row=0;row<99;++row) {
        unsigned next=row+1;
        if(next<99) {
            ld_launch(base,1u);
            if(next+1u<99) {
                ld_prepare(base,input+(next+1u)*32u,32u);
            }
            rc=ld_join(base);if(rc)return rc;
        }
        transport_output(base,output+row*256u,256u);
    }
    return wait_state(d,64u);
}
