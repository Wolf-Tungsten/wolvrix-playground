/* Deterministic, continuously active scalar/vector multiply workload. */
.section .text.init
.globl _start
.option norvc
_start:
  la t0, unexpected_trap
  csrw mtvec, t0
  li t0, 0x6600
  csrs mstatus, t0
  csrw fcsr, zero
  csrw vcsr, zero
  la s0, operands
  li a1, 0x8123456789abcdef
  li a2, 0x7192837465abcdef
  li s1, 0
.globl multiply_loop
multiply_loop:
  mul a3, a1, a2
  mulh a4, a1, a2
  mulhsu a5, a1, a2
  mulhu a6, a1, a2
  mulw a7, a1, a2
  andi t0, a1, 127
  mulw t0, t0, a2
  xor a1, a3, a5
  add a2, a2, a6

  fld f0, 0(s0)
  fld f1, 8(s0)
  fld f2, 16(s0)
  fmul.d f3, f0, f1
  fmadd.d f4, f0, f1, f2
  fmsub.d f5, f0, f1, f2
  fnmadd.d f6, f0, f1, f2
  fnmsub.d f7, f0, f1, f2
  flw f0, 24(s0)
  flw f1, 28(s0)
  flw f2, 32(s0)
  fmul.s f3, f0, f1
  fmadd.s f4, f0, f1, f2
  fmsub.s f5, f0, f1, f2
  fnmadd.s f6, f0, f1, f2
  fnmsub.s f7, f0, f1, f2

  .macro integer_vector sew
  vsetvli t1, zero, \sew, m1, tu, mu
  vmv.v.x v1, a1
  vmv.v.x v2, a2
  vmv.v.i v3, 3
  vmul.vv v4, v1, v2
  vmulh.vv v5, v1, v2
  vmulhu.vv v6, v1, v2
  vmulhsu.vv v7, v1, v2
  vmacc.vv v3, v1, v2
  vnmsac.vv v3, v1, v2
  vmadd.vv v3, v1, v2
  vnmsub.vv v3, v1, v2
  vsmul.vv v8, v1, v2
  .endm
  integer_vector e8
  integer_vector e16
  integer_vector e32
  integer_vector e64

  vsetvli t1, zero, e16, m1, tu, mu
  vmv.v.x v1, a1
  vmv.v.x v2, a2
  vwmul.vv v4, v1, v2
  vwmulu.vv v6, v1, v2
  vwmulsu.vv v8, v1, v2
  vwmacc.vv v4, v1, v2
  vwmaccu.vv v6, v1, v2
  vwmaccsu.vv v8, v1, v2

  .macro floating_vector sew, load, offset
  vsetvli t1, zero, \sew, m1, tu, mu
  addi t2, s0, \offset
  \load v1, (t2)
  \load v2, (t2)
  \load v3, (t2)
  vfmul.vv v4, v1, v2
  vfmacc.vv v3, v1, v2
  vfnmacc.vv v3, v1, v2
  vfmsac.vv v3, v1, v2
  vfnmsac.vv v3, v1, v2
  vfmadd.vv v3, v1, v2
  vfnmadd.vv v3, v1, v2
  vfmsub.vv v3, v1, v2
  vfnmsub.vv v3, v1, v2
  .endm
  floating_vector e16, vle16.v, 48
  floating_vector e32, vle32.v, 64
  floating_vector e64, vle64.v, 80

  vsetvli t1, zero, e16, m1, tu, mu
  addi t2, s0, 48
  vle16.v v1, (t2)
  vle16.v v2, (t2)
  vfwmul.vv v4, v1, v2
  vfwmacc.vv v4, v1, v2
  vsetvli t1, zero, e32, m1, tu, mu
  addi t2, s0, 64
  vle32.v v1, (t2)
  vle32.v v2, (t2)
  vfwmul.vv v4, v1, v2
  vfwmacc.vv v4, v1, v2
  addi s1, s1, 1
  andi t1, s1, 3
  csrw vxrm, t1
  j multiply_loop
.globl multiply_loop_end
multiply_loop_end:
unexpected_trap:
  li a0, 1
  .word 0x0000006b
  j unexpected_trap

.section .rodata
.balign 16
operands:
  .quad 0x3ff0000000000001, 0xbfefffffffffffff, 0x3cb0000000000000
  .word 0x3f800001, 0xbf7fffff, 0x33800000
  .zero 12
  .half 0x3c01, 0xbc01, 0x0001, 0x0400, 0x7bff, 0x0000, 0x8000, 0x3bff
  .word 0x3f800001, 0xbf800001, 0x00800000, 0x00000001
  .quad 0x3ff0000000000001, 0xbff0000000000001
