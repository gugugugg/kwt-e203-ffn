#include "kwt_driver.h"
/* These addresses belong only to this public-E203 development harness. */
#define ACCEL_BASE ((uintptr_t)0x10040000u)
#define MAIL_BASE ((uintptr_t)0x10041000u)
#define SHARED_BASE ((uintptr_t)0xa0000000u)
static void mb_write(unsigned off,uint32_t value) { *(volatile uint32_t *)(MAIL_BASE+off)=value; }
static uint32_t mb_read(unsigned off) { return *(volatile uint32_t *)(MAIL_BASE+off); }
static void io_write(unsigned off,uint32_t value) { *(volatile uint32_t *)(ACCEL_BASE+off)=value; }
static void fence_io(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
/* Explicit CPU writes clear all task data/parameter slots before a fresh task.
   No matrix multiplication, dot product, normalization or reference answer here. */
static void clear_accelerator(void) {
    const unsigned lengths[3]={6336u,16384u,1024u};
    for(unsigned kind=0;kind<3;++kind) {
        io_write(8,kind); io_write(12,0);
        for(unsigned i=0;i<lengths[kind];++i) io_write(16,0);
    }
    fence_io();
}
int main(void) {
    kwt_device device={ACCEL_BASE,1000000u};
    const uint32_t tasks=mb_read(12);
    for(uint32_t task=0;task<tasks;++task) {
        mb_write(16,1); clear_accelerator();
        mb_write(0,task); fence_io();
        while(mb_read(4)!=task+1u) { }
        mb_write(16,2); fence_io();
        int rc=kwt_ffn_run(&device,(const int16_t *)(SHARED_BASE+0x0000u),
                           (const int16_t *)(SHARED_BASE+0x4000u),
                           (const int64_t *)(SHARED_BASE+0xc000u),
                           (int8_t)mb_read(44),(int16_t *)(SHARED_BASE+0x10000u));
        if(rc) { mb_write(20,(uint32_t)rc); for(;;) { } }
        fence_io(); mb_write(8,task); fence_io();
    }
    mb_write(24,0xcafe1234u);
    return 0;
}
