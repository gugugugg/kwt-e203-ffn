#include "kwt_encoder_driver.h"
#include "../cpu_integration/kwt_platform_addresses.h"
#define MAIL ((uintptr_t)KWT_MAIL_BASE)
#define SHARED ((uintptr_t)KWT_SHARED_BASE)
static void mb_write(unsigned off,uint32_t value) { *(volatile uint32_t *)(MAIL+off)=value; }
static uint32_t mb_read(unsigned off) { return *(volatile uint32_t *)(MAIL+off); }
static void fence_io(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static int stage_layer(void *context,unsigned layer,const uint16_t **parameters,const uint16_t **config) {
    (void)context;
    mb_write(48,layer); fence_io();
    while(mb_read(52)!=layer+1u) { }
    *parameters=(const uint16_t *)(SHARED+0x20000u);
    *config=(const uint16_t *)(SHARED+0x3a000u);
    return KWE_OK;
}
int main(void) {
    const kwe_device device={KWT_ACCEL_BASE,1000000u};
    const uint32_t count=mb_read(12);
    for(uint32_t task=0;task<count;++task) {
        mb_write(0,task); fence_io();
        while(mb_read(4)!=task+1u) { }
        int rc=kwe_run(&device,(const int16_t *)(SHARED+0),
                       (const uint16_t *)(SHARED+0x4000u),(const uint16_t *)(SHARED+0x9000u),
                       stage_layer,0,(int16_t *)(SHARED+0x10000u));
        if(rc) { mb_write(20,(uint32_t)rc); for(;;) { } }
        mb_write(8,task); fence_io();
    }
    mb_write(24,0xcafe1234u);
    return 0;
}
