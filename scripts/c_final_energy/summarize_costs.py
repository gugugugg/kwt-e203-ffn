"""Use own native W12 and preserve missing baseline cell attribution explicitly."""
from pathlib import Path
import csv,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_final_energy import REPORT,dump

def components(row):
    tag=json.loads((ROOT/row['profile']).read_text())['tag'];folder=ROOT/'reports/optimization/complete_soc'/row['variant']
    tasks=[t for p in folder.glob('task_*.json') for t in json.loads(p.read_text())['tasks']];energy={};counts={};unknown=[]
    for task in tasks:
        base=ROOT/'reports/server'/('complete_soc_sm40_'+tag)/('power_%d'%task['case']);files=list(base.glob('*shift_cells.tsv'));roles={}
        if len(files)!=1:unknown.append(dict(case=task['case'],reason='No unique existing shift-cell export'));continue
        with files[0].open() as stream:
            for cell in csv.DictReader(stream,delimiter='\t'):
                role=cell['role'];roles[role]=roles.get(role,0)+1
                if cell['total_w']=='NA':unknown.append(dict(case=task['case'],cell=cell['cell'],value='NA'));continue
                energy[role]=energy.get(role,0)+float(cell['total_w'])*task['cycles']/150000000/12
        counts[str(task['case'])]=roles
    return dict(mean_energy_j=energy,counts=counts,unknown=unknown,unseparated_mean_energy_j=row['mean_energy_j']-sum(energy.values()),source='Existing native per-cell attributes over own full task; unknowns not zero filled')

def main():
    selection=json.loads((REPORT/'final-selection.json').read_text());base=selection['baseline'];rows=[base]+selection['candidates'];out=[]
    for row in rows:
        comp=components(row)
        out.append(dict(variant=row['variant'],cycles=row['cycles'],throughput_per_second=row['throughput_per_second'],mean_energy_j=row['mean_energy_j'],mean_power_w=row['mean_power_w'],scoring_area_mm2=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'],components=comp,module_mean_energy_j=row.get('module_mean_energy_j',{}),delta_energy_j=row['mean_energy_j']-base['mean_energy_j']))
    result=dict(baseline=out[0],candidates=out[1:],target_met=selection['target_met'],recommendation=selection['recommended_energy_candidate'],publication_changed=False,published_variant='ffn_wen_C',model_selection=json.loads((REPORT/'models/selection.json').read_text()),baseline_shift_FF_power_available='shift_state_register' in out[0]['components']['mean_energy_j'],new_FF_power_not_subtracted_from_missing_baseline=True)
    dump(REPORT/'cost-attribution.json',result)
    lines=['# C最后一轮能耗优化实测结果','','|版本|完整周期|tasks/s|任务能耗μJ|加权平均功率mW|计分面积mm²|相对C能耗nJ|','|---|---:|---:|---:|---:|---:|---:|']
    for r in out:
        cycles=str(r['cycles'][0])+' ×12' if len(set(r['cycles']))==1 else str(r['cycles'])
        lines.append('|%s|%s|%.12f|%.12f|%.12f|%.9f|%+.12f|'%(r['variant'],cycles,r['throughput_per_second'],r['mean_energy_j']*1e6,r['mean_power_w']*1e3,r['scoring_area_mm2'],r['delta_energy_j']*1e9))
    lines+=['','SS按消费生命周期共享shift；O1只旁路已有FIFO头，两项独立不组合。宏访问和模型周期不当作功耗结果。','发布C及W/C16/IR回退保持。各候选使用自身最终网表/完整CPU12/原生W12/正式SS150/三证明和mapped。', '原C没有独立shift FF功耗导出；该缺失保留，不重跑旧PPA、不按新增候选FF局部值直接扣旧整机。不同版本只比较共同已有角色；混合桶不全部归为乘法器、时钟或选择器。','']
    for r in out:
        lines+=['## '+r['variant'],'','|原生可分离角色|nJ/任务|','|---|---:|']
        for role,value in r['components']['mean_energy_j'].items():lines.append('|%s|%.9f|'%(role,value*1e9))
        lines.append('|未分离其余区域|%.9f|'%(r['components']['unseparated_mean_energy_j']*1e9));lines.append('')
    lines+=['## 原生模块分组相对C变化','','|分组|O1变化nJ/任务|SS变化nJ/任务|','|---|---:|---:|']
    by_name={r['variant']:r for r in out}
    for role,base_value in out[0]['module_mean_energy_j'].items():
        changes=[(by_name[n]['module_mean_energy_j'].get(role,0)-base_value)*1e9 for n in ['ffn_cfe_O1','ffn_cfe_SS']]
        lines.append('|%s|%+.9f|%+.9f|'%(role,changes[0],changes[1]))
    lines+=['','O1的stash分组确实下降，但共享SRAM、CPU等分组增量使整机能耗仍上升；SS的accelerator_other分组下降，但CPU等分组增量抵消。分组是该最终网表的原生属性归属，含时钟、缓冲和综合重组影响，不能把差额全部归因到旁路选择、共享shift或某一次尺寸修复。整机判定始终使用原生total_w，分组求和的表示残差另存，不倒改原W。','']
    lines+=['若没有满足E严格下降/A预算/T>=1000的候选，只进入面积优化规划；本轮负结果不意味着工艺极限，也不自动放宽能耗约束。' if not selection['target_met'] else '完整验收合格项只提供发布建议，不自动切换。']
    (REPORT/'cost-attribution.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    dump(REPORT/'version-parameters.json',dict(experiment='ffn_c_final_energy',numerical_model='Q2/int16 effective36 exact RNE/saturation',MACs=32,clock_hz=150000000,corner='SS 0.99V 125C OCV EMA2',cold_task='11936payload+5guard+5control through last physical SRAM write commit; ACK separate',versions=out,published_variant='ffn_wen_C',fallbacks=['ffn_ce_W','ffn_cp_C16','ffn_lp_IR']))
    print('C_FINAL_ENERGY_COSTS',json.dumps(dict(target_met=selection['target_met'],recommendation=selection['recommended_energy_candidate'])),flush=True)

if __name__=='__main__':main()
