# 基于 E203 的 KWT-1 离线语音指令识别加速器

本项目面向 KWT-1 语音指令识别模型，把编码器前馈网络的第一层全连接计算（FC1）集成到 E203 SoC。仓库同时保存了最终选用的 **MGPR**、历次发布的 RTL、驱动、数值参考和架构实验。第一次阅读可以从 [MGPR 计算核心](build/optimization/rtl_sources/ffn_ag_mgpr/encoder/kwt_threebank_core.sv) 和 [SoC 顶层](build/optimization/complete_soc/ffn_ag_mgpr/kwt_complete_soc.sv) 开始。

## 一个任务算什么

一次任务接收 99 行、每行 64 个 INT16 输入，乘以一组 64×256 的权重，加上 256 个逐列偏置，产生完整的 **99×256 矩阵**。每个输出含 64 个乘积和一次偏置。验收从第一笔必要装载计到最后一笔结果写入物理共享 SRAM，包括搬运、总线等待、调度和计算。下文的 tasks/s 均指这个 FC1 工作量。数值路径采用有效 36 位累加、最近偶数舍入和 INT16 饱和。[数值与装载格式](numeric/格式说明.md)

## 最终版本怎样省电

MGPR 使用原 32 位 System Bus 和 64 路 MAC。最后三版在同一 150 MHz 条件下跑完 12 项完整冷任务，总周期均为 **545,208 拍**，吞吐均为 **3,301.49 tasks/s**。在这个共同基线上，可以直接看出两次修改的代价和收益。

| 版本 | 主要变化 | 计分面积（mm²） | 整机平均功率（mW） | 单任务能耗（μJ） |
|---|---|---:|---:|---:|
| CH | 无损输入编码，片上恢复 INT16 输入 | 0.378665 | 46.0002 | 13.9332 |
| AG | 按有效乘加和行资格，对累加寄存器分组开钟 | 0.364551 | 42.0670 | 12.7418 |
| **MGPR** | 40 颗私有 SRAM 按访问开钟，预测缓存改用单口 SRAM | **0.357868** | **38.9823** | **11.8075** |

从 AG 到 MGPR，12 项任务中原 40 颗私有 SRAM 的时钟上升沿由 **21,808,320** 次降到 **4,653,312** 次。整机功率和单任务能耗均下降 **7.33%**，计分面积下降 **1.83%**。功率取自最终网表完整冷窗的门级 SAIF，经 PTPX averaged 按各任务周期加权。MGPR 在 SS/EMA2 150 MHz 下的建立、保持余量分别为 +0.527496 ns 和 +0.144989 ns。[CH 与 AG 对照](reports/optimization/ffn_ch_efficiency/screening-summary.md) · [MGPR 验收数据](selection.json)

## 在自己的机器上运行

```sh
git clone https://github.com/gugugugg/kwt-e203-ffn.git
cd kwt-e203-ffn
```

**运行 RTL 示例。** 安装 Icarus Verilog 后，在仓库根目录执行以下命令即可运行早期点积单元的 228 组内置向量，覆盖输入间隙、输出背压、复位及连续任务。成功时终端会显示 `PASS dot64: 228 cases`。

```sh
iverilog -g2012 -I build/rtl/vectors -s kwt_dot64_tb -o dot64.vvp rtl/kwt_requantize.sv rtl/kwt_dot64.sv tb/rtl/kwt_dot64_tb.sv
vvp dot64.vvp
```

**运行完整 FC1 定点参考。** 安装 Python 3 和 NumPy，将自己的整数数组保存为 `codes.npz`。四个键为 `input`、`weight`、`bias`、`shift`，形状依次为 `(99,64)`、`(64,256)`、`(256,)`、`(256,)`。以下命令生成行主序的小端 INT16 输出，每任务 50,688 字节。

```sh
python numeric/fixed_reference.py codes.npz result.bin
```

## 怎样找一个历史版本

| 想查什么 | 从这里开始 |
|---|---|
| 某个发布版本的参数和成绩 | [19 个发布与提交归档](history/releases.json) · [逐版参数](history/release-metrics.json) |
| 某一轮尝试过哪些候选 | [早期 14 轮候选表](history/candidates.csv) · [逐轮配置](history/rounds)。表中 424 条记录对应 170 个不同候选名，同一版可在下一轮作为对照 |
| 某个版本对应哪份 RTL | 在[源码快照索引](history/snapshots.json)中搜索版本名。35 个按保存的父版和生成脚本重新导出的候选标为 `regenerated-from-recipe` |
| 提交工程包实际采用了哪些 RTL 文件 | [工程包源码对照](history/submission-sources.json)，最终版查 `MGPR-1` |
| 未发布的架构试验和小模块筛选 | [71 项研究目录](history/studies.json) · [收录范围](history/coverage.json)。跨版本比较时须核对总线、装载和计时条件 |

## 复现环境与许可

公共 RTL、固件和台架分别位于 [rtl](rtl)、[software](software) 和 [tb](tb)。复现整机综合、时序和功耗需配置相应 EDA 工具，以及自行取得授权的标准单元、SRAM/ROM 模型和时序库；历史文件表中的库路径需映射到本机。[MGPR 整机文件表与脚本](build/optimization/complete_soc/ffn_ag_mgpr)

自研代码使用 [MIT 许可证](LICENSE)。E203 派生文件保留 Nuclei 的版权声明及 [Apache-2.0 许可证](licenses/Apache-2.0.txt)。上游项目见 [Nuclei Hummingbirdv2](https://github.com/riscv-mcu/e203_hbirdv2) 和[冻结版本的 Keyword Transformer](https://github.com/ARM-software/keyword-transformer/tree/237e4097afd4f6851e0b82f0a8d65c2dfe8eae30)。
