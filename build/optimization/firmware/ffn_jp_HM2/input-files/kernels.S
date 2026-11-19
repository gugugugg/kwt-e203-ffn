.text
.option push
.option rvc
.option norelax
.align 2
.globl kwt_transport_load4
.type kwt_transport_load4,@function
kwt_transport_load4:
 beqz a2,2f
 slli a6,a2,2
 add a6,a1,a6
1:
 c.lw a2,0(a1)
 c.lw a3,4(a1)
 c.lw a4,8(a1)
 c.lw a5,12(a1)
 c.sw a2,0(a0)
 c.sw a3,0(a0)
 c.sw a4,0(a0)
 c.sw a5,0(a0)
 c.addi a1,16
 bne a1,a6,1b
2:
 ret
.size kwt_transport_load4,.-kwt_transport_load4
.align 2
.globl kwt_transport_output4
.type kwt_transport_output4,@function
kwt_transport_output4:
 beqz a2,2f
 slli a6,a2,2
 add a6,a1,a6
1:
 c.lw a2,0(a0)
 c.lw a3,0(a0)
 c.lw a4,0(a0)
 c.lw a5,0(a0)
 c.sw a2,0(a1)
 c.sw a3,4(a1)
 c.sw a4,8(a1)
 c.sw a5,12(a1)
 c.addi a1,16
 bne a1,a6,1b
2:
 ret
.size kwt_transport_output4,.-kwt_transport_output4
.option pop
