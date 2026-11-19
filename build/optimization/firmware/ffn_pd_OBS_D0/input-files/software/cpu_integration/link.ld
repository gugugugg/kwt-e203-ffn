OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
    ITCM (rwx) : ORIGIN = 0x80000000, LENGTH = 64K
    DTCM (rw)  : ORIGIN = 0x90000000, LENGTH = 64K
}
SECTIONS {
    .text : { KEEP(*(.init)) *(.text .text.*) *(.rodata .rodata.*) } > ITCM
    .data : { *(.sdata .sdata.* .data .data.*) } > ITCM
    .bss (NOLOAD) : { . = ALIGN(4); __bss_start = .; *(.sbss .sbss.* .bss .bss.* COMMON) . = ALIGN(4); __bss_end = .; } > DTCM
    __global_pointer$ = ORIGIN(DTCM) + 0x800;
    __stack_top = ORIGIN(DTCM) + LENGTH(DTCM) - 16;
    /DISCARD/ : { *(.comment .eh_frame .riscv.attributes) }
}
