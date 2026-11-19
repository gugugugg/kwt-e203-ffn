"""Summarize the fixed queue model and verify its research archive on E and G."""
import csv
import filecmp
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_sr_storage_study'
ARCHIVE = Path('G:/xpian_历史版本库/研究与规划/ffn_sr_storage_study')
TAG = 'complete_soc_sm40_opt_ffn_ara_SR_drive_v2_final_ss_ema2'
RELEASE = ROOT / 'reports/submission/ara-SR-release-20261105/completion.json'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def area_evidence():
    report = ROOT / 'reports/server' / TAG
    hierarchy = (report / 'area.rpt').read_text(encoding='utf-8').splitlines()
    macro_rows = (report / 'macros.rpt').read_text(encoding='utf-8').splitlines()
    netlist = (ROOT / 'build/server' / TAG / 'netlist.v').read_text(encoding='utf-8')
    prefixes = ('/output_queue/row_stash_2__gate', '/output_queue/row_stash_2__memory')
    area_rows = {suffix: next(hierarchy[i + 1] for i, line in enumerate(hierarchy)
                              if line.endswith(suffix)) for suffix in prefixes}
    area_rows = {key: float(row.split()[0]) for key, row in area_rows.items()}
    macro_i = next(i for i, line in enumerate(macro_rows)
                   if '/output_queue/row_stash_2__memory/macro_wrapper/macro' in line)
    ff = re.findall(r'^\s*(\w+_12TR40) (row0_(?:read|write|count)_reg_\d+_) ', netlist, re.M)
    with (ROOT / 'reports/optimization/ffn_sr_area/library/cells.tsv').open() as f:
        library = {row['ref']: float(row['area_um2']) for row in csv.DictReader(f, delimiter='\t')}
    geom = ROOT / 'reports/optimization/ffn_logic_power/diagnosis/ffn_jp_HM2/private_leaf_power.tsv'
    with geom.open() as f:
        gate = next(row for row in csv.DictReader(f, delimiter='\t')
                    if row['ref_name'] == 'NAND2V0_12TR40')
    ff_area = sum(library[ref] for ref, _ in ff)
    removed = round(sum(area_rows.values()) + ff_area, 6)
    mux_reference = round(32 * 3 * float(gate['area_um2']), 6)
    return dict(implementation_tag=TAG, macro_report_lines=macro_rows[macro_i:macro_i + 3],
                macro_area_um2=float(macro_rows[macro_i + 2].strip()),
                removed_memory_wrapper_including_macro_um2=area_rows[prefixes[1]],
                removed_macro_icg_um2=area_rows[prefixes[0]], removed_state_cells=ff,
                removed_state_cell_area_um2=round(ff_area, 6),
                deleted_area_identified_um2=removed,
                deleted_other_logic_without_area_credit=['row0 pointer and count update', 'row0 memory address mux and enables',
                                                         'row0 return branch'],
                retained=['FIFO16 and existing head selector', 'two held words', 'two row1 macros and pending path'],
                added=['single-word take qualifier', 'append select for either existing held word',
                       'modified FIFO capacity control and select buffering'],
                conservative_datapath_mux_count_reference=32,
                nand2_v0_um2=float(gate['area_um2']),
                datapath_mux_geometry_reference_um2=mux_reference,
                remaining_area_after_datapath_reference_um2=round(removed - mux_reference, 6),
                added_control_buffer_and_timing_repair_area_um2=None, measured_net_area_mm2=None,
                sources=dict(area=str(report / 'area.rpt'), macro=str(report / 'macros.rpt'),
                             netlist=str(ROOT / 'build/server' / TAG / 'netlist.v'),
                             flipflop=str(ROOT / 'reports/optimization/ffn_sr_area/library/cells.tsv'),
                             nand2=str(geom)))


def verify_sync():
    source = sorted(path.relative_to(REPORT) for path in REPORT.rglob('*') if path.is_file())
    target = sorted(path.relative_to(ARCHIVE) for path in ARCHIVE.rglob('*') if path.is_file())
    if source != target or any(not filecmp.cmp(REPORT / path, ARCHIVE / path, shallow=False) for path in source):
        raise RuntimeError('E/G archive differs')
    return source


def main():
    release, model = load(RELEASE), load(REPORT / 'model-results.json')
    actual = load(ROOT / 'reports/optimization/ffn_ar_area/ffn_ara_SR.json')
    intervals = actual['loading_dma_counts']
    phases = actual['phases']
    if (len(intervals) != 12 or intervals.keys() != phases.keys()
            or any(r['last_commit'] != 98782 or r['last_ack'] != 98784 for r in intervals.values())
            or any(r['first_mac'] != 29895 or r['last_emit'] != 98754 for r in phases.values())):
        raise RuntimeError('SR archived intervals differ from the calibration')
    area = area_evidence()
    write(REPORT / 'cost-ledger.json', area)
    write(REPORT / 'sr-baseline.json', dict(release=release, loading_dma_counts=intervals, phases=phases,
        source='reports/optimization/ffn_ar_area/ffn_ara_SR.json'))
    for filename in ('screen.py', 'finish.py'):
        shutil.copyfile(Path(__file__).with_name(filename), REPORT / filename)
    candidates, normal = model['cold_results'], model['normal_scenarios']
    case = candidates[0]
    cold_ok = sum(r['passed'] for r in candidates)
    normal_ok = sum(r['passed'] for r in normal)
    fields = dict(cold_passed=cold_ok, normal_scenarios_passed=normal_ok,
                  cold_ordered_results=sum(r['outputs'] for r in candidates if r['passed']),
                  normal_ordered_results=sum(f['outputs'] for r in normal if r['passed'] for f in r['frames']),
                  odd_pair_pops=sum(f['queue_evidence']['events']['odd_pair_pops']
                                    for r in normal if r['passed'] for f in r['frames']),
                  candidate_throughput=model['candidate_throughput'],
                  sr_throughput=release['throughput_tasks_per_second'],
                  recommended_for_hardware=model['timing_eligible'] and
                      area['remaining_area_after_datapath_reference_um2'] > 0,
                  release=release['variant'])
    write(REPORT / 'selection.json', fields)
    if not (model['functional_passed'] and cold_ok == 12 and normal_ok == 3):
        raise RuntimeError('Incomplete functional evidence; consult preserved model results')
    q = case['queue_evidence']['events']
    baseline_cycles = release['cycles'][0]
    slowdown = (1 - model['candidate_throughput'] / release['throughput_tasks_per_second']) * 100
    result = f"""# SR 首行输出暂存 SRAM 筛选

**结论：不推荐这套 FIFO16 直连方案进入硬件。** 功能通过，模型吞吐高于 1000 tasks/s，但比 SR 低 {slowdown:.2f}%，未达到本轮保住 SR 吞吐的放行条件。发布继续使用 SR。

|指标|SR 基线|FIFO16 直连模型|
|---|---:|---:|
|完整冷任务周期（各 12 项相同）|{baseline_cycles:,}|{case['cold_cycles']:,}|
|12 项总周期|{model['sr_cycles_total']:,}|{model['candidate_cycles_total']:,}|
|吞吐（tasks/s）|{release['throughput_tasks_per_second']:.6f}|{model['candidate_throughput']:.6f}|
|代表任务物理写提交 / ACK|98782 / 98784|{case['final_physical_commit']} / {case['final_ack']}|
|计分面积（mm²）|{release['scoring_area_mm2']:.9f}|未测量|
|任务能耗（μJ）|{release['mean_energy_j']*1e6:.9f}|未测量|

## 进展与端口

- 冷窗口模型核对 {fields['cold_ordered_results']:,} 项有序结果和每一笔最终物理写入的地址与数值。每任务 DMA 读 11,936 次、写 12,672 次、102 个 descriptor、host 写 11,946 次。首个 MAC 仍是第 {case['first_mac']} 拍。
- 单字读、混合读及暂停 4096 拍各连续运行 12 个任务，核对 {fields['normal_ordered_results']:,} 项结果，覆盖 {fields['odd_pair_pops']:,} 次奇数读位置成对消费及第 98 行。
- 首行仍以成对写入 FIFO，每拍从旧 FIFO 头向 held 送一字，先收已在路上的第二行返回。第二行两颗单端口宏遇写让读，同步返回占用 pending。每任务首行直连 12,800 字，第二行读写各 12,544 字。FIFO 和第二行宏分别达到 16、256 项，held 与 pending 合计最多两项。
- 代表任务首行量化等待 {q['row0_quant_wait']:,} 拍。其中 {q['row0_wait_held_full']:,} 拍 held 与已预留返回占满，{q['row0_wait_older_row1']:,} 拍虽有空间但按顺序须先交付第二行旧结果。其余 {q['row0_quant_wait']-q['row0_wait_held_full']-q['row0_wait_older_row1']:,} 拍空间及行序允许取一字，但满 FIFO 仅释放一格，当前量化需要同时入两字。SR 校准模型的总量化等待为 4042 拍，本模型为 {case['counts']['quant_blocked']:,} 拍；最终净增 {case['cold_cycles']-baseline_cycles:,} 拍。

## 同库面积账

- 宏本体 {area['macro_area_um2']:.6f} μm²，连 wrapper {area['removed_memory_wrapper_including_macro_um2']:.4f} μm²，另有独立 ICG {area['removed_macro_icg_um2']:.4f} μm²，以及最终网表上的 {len(area['removed_state_cells'])} 个指针/计数触发器共 {area['removed_state_cell_area_um2']:.4f} μm²。已识别删除项合计 {area['deleted_area_identified_um2']:.4f} μm²。原读写控制及返回选择的删除收益未计。
- FIFO 头选择复用。按 held 两组 16 位都需要新增一个数据选择层估算，同库 NAND2 等效几何参考 {area['datapath_mux_geometry_reference_um2']:.4f} μm²。扣除该参考后有 {area['remaining_area_after_datapath_reference_um2']:.4f} μm² 覆盖新资格、容量控制、缓冲与时序修复。后三者未映射，净面积与整机能耗未知。

## 复现

在 E:\\xpian 运行 `python -B scripts/sr_storage_study/screen.py`。入口复用 `scripts/c16_efficiency/models.py`、`scripts/column_parallel` 和 `scripts/taskflow_study` 中的冻结模型。用归档原生 case1 的主机前缀和 CPU 请求间隔，变体自行计算 ready、端口仲裁与同步返回。其他任务替换各自 payload，沿用外部 CPU 间隔假设。源轨迹位于 `reports/optimization/ffn_taskflow_study/native-evidence/reports/optimization/ffn_taskflow_study/native-events.csv`，输入位于 `build/optimization/ffn_transport/testdata`。本次结果为模型筛选，SR 的正式 E203 成绩来自既有发布记录。
"""
    (REPORT / 'final-report.md').write_text(result, encoding='utf-8')
    shutil.copytree(REPORT, ARCHIVE, dirs_exist_ok=True)
    files = [path for path in verify_sync() if path.name != 'local-sync.json']
    receipt = dict(passed=True, byte_for_byte=True, files_including_receipt=len(files) + 1,
                   evidence_bytes_excluding_receipt=sum((REPORT / path).stat().st_size for path in files),
                   source=str(REPORT), archive=str(ARCHIVE))
    write(REPORT / 'local-sync.json', receipt)
    shutil.copyfile(REPORT / 'local-sync.json', ARCHIVE / 'local-sync.json')
    verify_sync()
    print(json.dumps(dict(**fields, synchronization=receipt), ensure_ascii=False))


if __name__ == '__main__':
    main()

