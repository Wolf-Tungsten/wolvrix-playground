OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ram (rwx) : ORIGIN = 0, LENGTH = 4M }
SECTIONS {
    .text 0x180 : { KEEP(*(.text.start)) *(.text .text.*) } > ram
    .rodata : { *(.rodata .rodata.* .srodata .srodata.*) } > ram
    .data : { *(.data .data.*) } > ram
    .sdata : { __global_pointer$ = . + 0x800; *(.sdata .sdata.*) } > ram
    .bss (NOLOAD) : ALIGN(4) {
        __bss_start = .; *(.sbss .sbss.* .bss .bss.* COMMON)
        . = ALIGN(4); __bss_end = .;
    } > ram
    __stack_top = ORIGIN(ram) + LENGTH(ram) - 16;
    /DISCARD/ : { *(.comment) *(.eh_frame*) }
}
