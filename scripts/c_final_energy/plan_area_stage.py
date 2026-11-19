"""Use completed negative-energy evidence to propose one next area direction only."""
import json,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_final_energy import REPORT,dump

def main():
    selection=json.loads((REPORT/'final-selection.json').read_text())
    if selection['target_met']:raise RuntimeError('This area transition applies to the approved no-energy-winner branch')
    base=selection['baseline'];a0=base['metrics']['area']['accelerator_budget_including_shared_interface_mm2'];rows=[]
    for r in selection['candidates']:
        if not r['mapped_passed']:raise RuntimeError('Complete representative mapped acceptance first')
        area=r['metrics']['area']['accelerator_budget_including_shared_interface_mm2']
        rows.append(dict(variant=r['variant'],area_mm2=area,area_delta_um2=(area-a0)*1e6,energy_j=r['mean_energy_j'],energy_delta_nj=(r['mean_energy_j']-base['mean_energy_j'])*1e9,throughput=r['throughput_per_second']))
    path=ROOT/'reports/optimization/ffn_w_energy/activity-mapping/native-review-first/ffn_wen_C/inventory.json'
    cells=json.loads(path.read_text())['cells'];refs=Counter(v['ref'] for k,v in cells.items() if '/accumulator_reg_' in k)
    proposal=dict(planning_only=True,new_RTL_or_EDA_started=False,published_variant='ffn_wen_C',current_experiment_closed_without_energy_winner=True,
        measured_tradeoffs=rows,next_direction='Private accumulator reset lifecycle: determine whether existing mandatory bias seed makes power-on/reset data state unobservable before use.',
        existing_accumulator_cells=dict(refs),state_width_unchanged=36,MACs_unchanged=32,clock_hz=150000000,
        proposed_scope='At most one independently approved area candidate from C; do not combine SS/O1, alter arithmetic, add state, macros or pipeline.',
        cost_not_yet_established=['Same-library/reset-vs-nonreset cell area and CK/D load at actual required drive','Seed-before-MAC/quant invariant under reset, pause, reload and row98','Whole-netlist timing repair and complete-task energy after any later approved implementation'],
        publication_rule='Keep C; preserve SS as a measured area/energy tradeoff. No opponent references means no invented aggregate score or automatic promotion.')
    dump(REPORT/'area-planning.json',proposal)
    lines=['# 下一阶段面积优化规划','','本轮SS/O1完整验收后均未达E严格下降要求，结束这轮能耗探索。当前C与W/C16/IR回退保持，以下仅规划，不生成面积RTL、不启动新CPU/DC/PT。','','|已测配置|计分面积mm²|相对C面积μm²|任务能耗μJ|相对C能耗nJ|tasks/s|','|---|---:|---:|---:|---:|---:|']
    for r in rows:lines.append('|%s|%.9f|%+.3f|%.12f|%+.9f|%.12f|'%(r['variant'],r['area_mm2'],r['area_delta_um2'],r['energy_j']*1e6,r['energy_delta_nj'],r['throughput']))
    lines+=['','SS实际删除128个shift FF和8颗pair shift ICG，面积下降但整机能耗上升；保留为后续面积—能耗取舍的真实参照。O1不作为面积起点。不得把局部结构删减直接解释为整机功耗原因，也不据此宣称工艺极限。','','## 一个优先核查的方向：按播种生命周期去除私有累加数据复位','','发布C的累加状态保持32×36位，现有代码在reset时清零、每tile正式MAC之前又逐pair写入完整bias。先从冻结C的真实网表和原始正常场景证明：任何合法MAC/量化消费前，该lane已完成本轮bias播种；重点包括复位中断、暂停恢复、重装和row98无效行。','','若该不变量成立，只研究私有accumulator数据FF的reset去除；FSM、协议、公共E203/外围、valid/reset控制、ICG资格和所有数值位宽保持。复用现有状态资格，不增valid寄存器；不与SS/O1组合，不扩大MAC/SRAM或扫描。当前真实累加FF构成：'+json.dumps(dict(refs))+'。','','## 先补成本账，再给实施方案','','1. 用C实际同库单元逐类比较reset/nonreset FF的面积、CK/D负载和所需驱动，计算ΣNref×(Areset−Anonreset)，未知项保留；不能用FF数量直接承诺净节省。','2. 计入复位分发、使能/反馈选择及后续150MHz保持/门控/电气修复的成本；面积范围若不能覆盖新增项，就保留负结果。','3. 数值/生命周期与成本均支持时，再提交仅一个候选的完整实施计划，仍要求32MAC、150MHz、同精度、完整冷窗口及≥1000tasks/s。后续优先降低面积且不增加任务能耗；如出现能耗取舍，先报告实测Pareto与正式计分盈亏条件，不自行放宽本轮能耗条件或切换发布。','','本轮没有对手参照，SS与C互有优劣，不能宣称SS正式综合分更高。下一阶段具体硬件实验尚未获本规划自动启动；C继续提交首选。','']
    (REPORT/'area-planning.md').write_text('\n'.join(lines),encoding='utf8');print('CFE_AREA_PLANNING_WRITTEN',dict(refs),flush=True)

if __name__=='__main__':main()
