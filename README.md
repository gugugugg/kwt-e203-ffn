# KWT-1 FFN accelerator on E203

这个仓库保存 2026 年嵌入式芯片与系统设计竞赛芯片设计赛道项目的自研源码及历史实验。一个任务计算单层 FC1：99×64 的输入与 64×256 的权重相乘，加上逐列偏置，输出 99×256 个结果。

## 从最终提交版开始

最终选用的 **MGPR** 通过原 32 位 System Bus 搬运数据，使用 64 路 MAC、分组累加器门控、按访问开钟的私有 SRAM，以及单口 SRAM 实现的输入预测缓存。验收采用 150 MHz，从必要装载计到最后一笔物理结果写入。

| 12 项完整冷任务 | MGPR |
|---|---:|
| 总周期 | 545,208 |
| 吞吐 | 3,301.49 tasks/s |
| 计分面积 | 0.357867926 mm² |
| 整机加权平均功率 | 38.982251 mW |
| 平均单任务能耗 | 11.807464 μJ |

代码入口：[计算核心和解码器](build/optimization/rtl_sources/ffn_ag_mgpr/encoder)、[SoC 接线和台架](build/optimization/complete_soc/ffn_ag_mgpr)、[数值与装载格式](numeric/格式说明.md)、[验收数据](selection.json)。结果采用有效 36 位累加、最近偶数舍入与 INT16 饱和。

## 历史版本怎么找

- [早期候选表](history/candidates.csv)逐轮列出 14 个批次的 424 条记录。同一候选可作为后续批次的对照，共有 170 个不同候选名。[逐轮参数](history/rounds)保留配置和测量口径。
- [源码索引](history/snapshots.json)按归档批次和版本名列出文件路径。共享文件只存一份；同路径但内容不同的历史文件位于 `snapshots/`。`frozen-parents` 表示冻结的父版副本，`regenerated-from-recipe` 表示从保留的生成器、父版与配置重新导出的源码。
- [发布目录](history/releases.json)列出从 IR 到 T＋R＋B 的 17 个编号发布版本，以及 AG、MGPR 两个提交归档。[版本参数](history/release-metrics.json)摘自各版归档。[研究目录](history/studies.json)还包括模型筛选、小模块试验和未发布的硬件候选。各阶段使用的总线、装载和计时条件请结合对应记录比较。
- [公共 RTL](rtl)、[驱动与固件](software)、[数值参考](sim)、[台架](tb)、[实验脚本](scripts)。历史源码在 `build/optimization` 下保留原始相对位置，便于读生成器和综合文件表。

## 运行定点参考

安装 Python 3 和 NumPy，准备一个 NPZ，包含 `input`、`weight`、`bias`、`shift` 四个整数数组，形状依次为 (99,64)、(64,256)、(256,)、(256,)。运行：

```sh
python numeric/fixed_reference.py codes.npz result.bin
```

输出为行主序的小端 INT16，共 50,688 字节。浮点参数转换、输入打包和移位格式见 [numeric](numeric)。

## 运行早期点积 RTL 示例

在仓库根目录用 Icarus Verilog 运行已有的 228 组点积向量。这组台架覆盖输入间隙、输出等待、复位和连续任务。

```sh
iverilog -g2012 -I build/rtl/vectors -s kwt_dot64_tb -o dot64.vvp rtl/kwt_requantize.sv rtl/kwt_dot64.sv tb/rtl/kwt_dot64_tb.sv
vvp dot64.vvp
```

## 工具和许可证

自研部分采用 [MIT](LICENSE)。源于 Nuclei Hummingbirdv2 的 E203 集成文件沿用文件头中的版权声明和 [Apache-2.0](licenses/Apache-2.0.txt)。本仓库内的这些子系统文件为项目使用的集成版本，完整上游 RTL 可从 [Nuclei Hummingbirdv2](https://github.com/riscv-mcu/e203_hbirdv2) 获取。浮点参考依赖 [Keyword Transformer](https://github.com/ARM-software/keyword-transformer/tree/237e4097afd4f6851e0b82f0a8d65c2dfe8eae30) 及其模型参数。

整机门级仿真与 PPA 复现需要自行配置授权的标准单元、SRAM/ROM 仿真模型、时序库和 EDA 工具，并把原始文件表中的库路径映射到本机。仓库提供接口、源码和选定的数值结果；工艺交付件、私有测量档案与参赛个人材料不随源码发布。
