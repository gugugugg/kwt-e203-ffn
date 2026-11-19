"""Summarize accepted native task measurements and separable shift-boundary costs."""
from pathlib import Path
import csv,json,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_energy import REPORT,dump

def components(row):
    folder=ROOT/'reports/optimization/complete_soc'/row['variant']
    tasks=[t for p in folder.glob('task_*.json') for t in json.loads(p.read_text())['tasks']]
    tag=json.loads((ROOT/row['profile']).read_text())['tag'];energy={};missing=[];counts={}
    for task in tasks:
        base=ROOT/'reports/server'/('complete_soc_sm40_'+tag)/('power_%d'%task['case'])
        files=list(base.glob('*shift_cells.tsv'))
        if len(files)!=1:
            missing.append(dict(case=task['case'],reason='No unique existing shift cell export'));continue
        roles={}
        with files[0].open() as stream:
            for cell in csv.DictReader(stream,delimiter='\t'):
                path=cell['cell'];role=None
                if 'jp_shift_return_reg_' in path:role='return_latches'
                elif path.endswith('/core/gate_shift_gate/cell_gate'):role='macro_clock_gate'
                elif 'pair_gate_shift_gate/cell_gate' in path:role='pair_state_clock_gates'
                elif cell['ref_name']=='RAMSP128X16' and 'shift_memory' in path:role='shift_macro'
                if role is None:continue
                roles[role]=roles.get(role,0)+1
                if cell['total_w']=='NA':missing.append(dict(case=task['case'],cell=path,role=role,value='NA'));continue
                energy[role]=energy.get(role,0.0)+float(cell['total_w'])*task['cycles']/150000000/12
        counts[str(task['case'])]=roles
    if missing:return dict(complete=False,missing=missing,partial_sums_j=energy,per_case_counts=counts)
    return dict(complete=True,mean_energy_j=energy,per_case_counts=counts,unseparated_mean_energy_j=row['mean_energy_j']-sum(energy.values()),source='Existing per-cell native W attributes, multiplied by each own cold-task cycle count; no new power measurement')

def main():
    selection=json.loads((REPORT/'final-selection.json').read_text());parent=selection['baseline'];rows=[parent]+selection['candidates'];out=[]
    for row in rows:
        out.append(dict(variant=row['variant'],cycles=row['cycles'],throughput_per_second=row['throughput_per_second'],mean_energy_j=row['mean_energy_j'],mean_power_w=row['mean_power_w'],scoring_area_mm2=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'],components=components(row)))
    candidate=out[1];base=out[0];delta=candidate['mean_energy_j']-base['mean_energy_j']
    result=dict(baseline=out[0],candidates=out[1:],energy_delta_j=delta,energy_delta_percent=100*delta/base['mean_energy_j'],target_met=selection['target_met'],published_variant='ffn_wen_C',publication_changed=False,XR_hardware_generated=False,XR_model_cycles=98824,XR_baseline_cycles=98783,XR_model_delta_per_task=41,all_negative_and_failed_evidence_retained=True)
    dump(REPORT/'cost-attribution.json',result)
    lines=['# C后续门控与跨行实验成本结果','','XR唯一模型每任务98824周期，比C慢41周期，因此未生成XR硬件。','','|版本|周期|tasks/s|平均任务能耗μJ|加权功率mW|计分面积mm²|','|---|---:|---:|---:|---:|---:|']
    for row in out:
        cycles=row['cycles'];label=str(cycles[0])+' ×12' if len(set(cycles))==1 else '/'.join(map(str,cycles))
        lines.append('|%s|%s|%.12f|%.12f|%.12f|%.9f|'%(row['variant'],label,row['throughput_per_second'],row['mean_energy_j']*1e6,row['mean_power_w']*1e3,row['scoring_area_mm2']))
    lines+=['','SL减C：%.12f nJ/任务（%+.12f%%），未达到严格降低任务能耗的目标。当前发布C及W/C16/IR回退保持。'%(delta*1e9,result['energy_delta_percent']),'','宏时钟门、16个pair shift状态门、16个返回锁存和shift宏均由本配置原生逐cell报告独立汇总。其余差额保留为未分离逻辑，不全部归为MAC或时钟。','']
    for row in out:
        comp=row['components'];lines.append(row['variant']+'：')
        if not comp['complete']:lines.append('现有逐cell导出不完整，缺失项保留在JSON中。')
        else:
            lines += ['','|区域|nJ/任务|','|---|---:|']
            for role,value in comp['mean_energy_j'].items():lines.append('|%s|%.9f|'%(role,value*1e9))
            lines.append('|未分离其余区域|%.9f|'%(comp['unseparated_mean_energy_j']*1e9))
        lines.append('')
    left,right=out[0]['components'],out[1]['components']
    if left['complete'] and right['complete']:
        boundary=(sum(right['mean_energy_j'].values())-sum(left['mean_energy_j'].values()))*1e9
        rest=(right['unseparated_mean_energy_j']-left['unseparated_mean_energy_j'])*1e9
        lines+=['逐cell已分离的shift边界合计变化%+.12f nJ/任务；未分离的其余区域变化%+.12f nJ/任务。两者相加为整机差额，不将未分离增量归因于某个未经独立分离的逻辑。'%(boundary,rest),'']
    (REPORT/'cost-attribution.md').write_text('\n'.join(lines),encoding='utf-8')
    dump(REPORT/'version-parameters.json',dict(experiment='ffn_c_energy',numerical_model='Q2 int16 effective36 exact RNE saturation',MACs=32,clock_hz=150000000,corner='SS 0.99V 125C OCV EMA2',cold_task='11936 payload + 5 guard + 5 control to final physical shared-SRAM write commit',versions=out,published_variant='ffn_wen_C',fallbacks=['ffn_ce_W','ffn_cp_C16','ffn_lp_IR']))
    print('C_ENERGY_COSTS',json.dumps({k:v for k,v in result.items() if k not in ['baseline','candidates']}),flush=True)

if __name__=='__main__':main()
