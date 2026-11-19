#include "kwt_platform_addresses.h"
    .section .init,"ax",@progbits
    .globl _start
_start:
    la sp, __stack_top
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    la t0, trap_handler
    csrw mtvec, t0
    csrw mie, zero
    la t0, __bss_start
    la t1, __bss_end
1:  bgeu t0, t1, 2f
    sw zero, 0(t0)
    addi t0, t0, 4
    j 1b
2:  call main
3:  wfi
    j 3b
    .balign 64
trap_handler:
    li t0, KWT_MAIL_BASE
    csrr t1, mcause
    sw t1, 0x20(t0)
    csrr t1, mepc
    sw t1, 0x24(t0)
    csrr t1, mtval
    sw t1, 0x28(t0)
    li t1, 0xdead0001
    sw t1, 0x14(t0)
4:  j 4b
