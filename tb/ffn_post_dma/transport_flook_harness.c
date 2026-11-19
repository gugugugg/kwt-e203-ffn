#include <windows.h>
#undef OUT
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "kwt_unified_driver.h"
static uint32_t desc_address,desc_words,active_address,active_words,active_direction,active_kind;
static unsigned kind,loaded[6],produced,starts,busy,prewrites,launches,task_number;
static void fail(const char *message){fprintf(stderr,"FLOOK_MODEL_FAIL %s task=%u kind=%u in=%u out=%u\n",message,task_number,kind,loaded[0],produced);exit(1);}
static uint32_t result_word(unsigned index){return 0x72000000u^(task_number<<16)^index;}
static void consume(uint32_t value){
    unsigned index=loaded[kind]++;
    uint32_t expected=(kind<<24)^(task_number<<16)^index;
    if(value!=expected)fail("payload order or descriptor snapshot changed");
    if(kind==0&&loaded[0]>(produced/128u+2u)*32u)fail("two input slots overfilled");
}
static uint32_t output_word(void){
    if(produced>=loaded[0]/32u*128u)fail("output requested before its row input");
    return result_word(produced++);
}
static void complete(void){
    if(!busy)fail("WAIT without current transfer");
    if(kind!=active_kind)fail("KIND changed while transfer was active");
    uint32_t *pointer=(uint32_t *)(uintptr_t)active_address;
    for(unsigned i=0;i<active_words;++i){
        if(active_direction==1)consume(pointer[i]);else pointer[i]=output_word();
    }
    busy=0;
}
static void transport_fence(void){}
static void transport_write(unsigned offset,uint32_t value){
    if(offset==0x40){desc_address=value;prewrites+=busy;return;}
    if(offset==0x44){desc_words=value;prewrites+=busy;return;}
    if(offset==0x48){
        if(busy)fail("launch while busy");
        active_address=desc_address;active_words=desc_words;active_direction=value;active_kind=kind;busy=1;++launches;return;
    }
    if(offset==0&&value==2){
        if(busy)fail("reset before completion");
        for(unsigned i=0;i<6;++i)loaded[i]=0;produced=0;starts=0;kind=0;return;
    }
    if(offset==8){if(busy)fail("KIND changed before join");kind=value;return;}
    if(offset==24){if(loaded[1]!=8704||loaded[5]!=64)fail("layer started before parameter load");++starts;return;}
    if(offset==48){consume(value);return;}
}
static uint32_t transport_read(unsigned offset){
    if(offset==0x50){complete();return 2;}
    if(offset==40)return 0x4b574531u;
    if(offset==20)return 0;
    if(offset==4||offset==36)return 2u|8u|16u|32u|64u;
    if(offset==52)return output_word();
    if(offset==32)return (uint16_t)output_word();
    return 0;
}
/* DRIVER */
static int stage(void *context,unsigned layer,const uint32_t **parameters,const uint32_t **shifts){
    (void)context;(void)layer;*parameters=(uint32_t *)(uintptr_t)0xa0020000u;*shifts=(uint32_t *)(uintptr_t)0xa003a000u;return 0;
}
int main(void){
    void *memory=VirtualAlloc((void *)(uintptr_t)0xa0000000u,524288,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(memory!=(void *)(uintptr_t)0xa0000000u)fail("shared model allocation");
    kwu_device device={0x10042000u};
    for(task_number=1;task_number<=2;++task_number){
        uint32_t *input=(uint32_t *)memory,*parameters=(uint32_t *)(uintptr_t)0xa0020000u,*shifts=(uint32_t *)(uintptr_t)0xa003a000u;
        uint32_t *output=(uint32_t *)(uintptr_t)0xa0010000u;
        for(unsigned i=0;i<3168;++i)input[i]=(task_number<<16)^i;
        for(unsigned i=0;i<8704;++i)parameters[i]=(1u<<24)^(task_number<<16)^i;
        for(unsigned i=0;i<64;++i)shifts[i]=(5u<<24)^(task_number<<16)^i;
        for(unsigned i=0;i<12672;++i)output[i]=0;
        if(kwu_run_linear(&device,input,stage,0,(int16_t *)output))fail("driver returned error");
        if(busy||loaded[0]!=3168||loaded[1]!=8704||loaded[5]!=64||produced!=12672||starts!=1)fail("complete task counts");
        for(unsigned i=0;i<12672;++i)if(output[i]!=result_word(i))fail("output address or row ordering");
    }
    printf("POST_DMA_FLOOK_PASS tasks=2 input_words=6336 output_words=25344 launches=%u busy_descriptor_writes=%u\n",launches,prewrites);
    return 0;
}
