# 4×32 私有 SRAM 门控整机结果

仅在输入、权重、结果暂存的 48 个私有 SRAM 宏上增加按访问开钟。对原 4×32 最终映射网表做时钟连线修改，撤销这 48 处连线和新增线网、单元即可逐字节恢复原私有核心。共享 SRAM、E203、计算、加载与写回逻辑沿用原网表。提交配置仍为 T＋R＋B（`ffn_sg_reuse`）。

| 指标 | 原 4×32 | 私有 SRAM 门控 |
|---|---:|---:|
| 12 项冷窗合计 | 172,128 拍 | 172,128 拍 |
| 150 MHz 吞吐 | 10,457.334 tasks/s | 10,457.334 tasks/s |
| 整机平均功率 | 69.554670 mW | 65.962083 mW |
| 平均单任务能耗 | 6.651281 μJ | 6.307734 μJ |
| 计分面积 | 0.525312030 mm² | 0.525541854 mm² |

12 项平均整机功率下降 **3.592587 mW（5.165%）**，每项功率均低于自己的原版对照。48 个 ICG 及配套反相器面积 **229.824 μm²**，较原版增加 **0.04375%**。实际内部功耗从 50.471517 mW 降至 46.887759 mW，解释了大部分整机差额。

SS/EMA2 150 MHz 建立 **+0.542085 ns**、保持 **+0.144989 ns**。全局电气、门控建立、门控保持及私有宏输入输出专项均无违例。原生 12 项逐位校验每项 **25,344 个结果**，均为 **14,344 拍**，最后物理写提交 **14,343 拍**、ACK **14,344 拍**。DMA 读 11,680 次、物理结果写和 ACK 各 12,672 次。所有私有宏每拍的有效时钟边沿均与访问请求对应。

功耗使用候选自己最终网表的 12 份冷窗门级 SAIF，以 PTPX averaged 模式计算。分布库延迟和原版一致，未做 SDF 回标。原生报告包已回传本机并逐文件核对。

[原生完整数值](received/measurement/native-evidence/reports/optimization/ffn_trb_4x32_private_sram/result.json) · [原生时序](received/measurement/native-evidence/reports/optimization/ffn_trb_4x32_private_sram/timing.json) · [网表改动清单](received/measurement/native-evidence/reports/optimization/ffn_trb_4x32_private_sram/eco.json) · [归档核对](received-measurement.json)
