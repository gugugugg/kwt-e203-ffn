"""Install native-confirmed W release bytes locally and synchronize the G release index."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,shutil

ROOT=Path(__file__).resolve().parents[2];R=ROOT/'reports/submission/w-release-20261104'
EXP=ROOT/'reports/optimization/ffn_c16_efficiency';G=Path('G:/xpian_历史版本库/提交版本/V003_ffn_ce_W');SNAP=G/'工程快照'

def load(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def same_copy(source,target):
    value=source.read_bytes();target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
    if target.read_bytes()!=value:raise RuntimeError('Release bytes differ '+str(target))

def main():
    src=EXP/'received/w-release-activation/native-evidence';native=load(src/'reports/submission/w-release-20261104/native-activation.json')
    if not native['complete'] or not native['selected_installed_last']:raise RuntimeError('Native W activation incomplete')
    records=[]
    for relative in native['installed']:
        p=src/relative
        if p.read_bytes()!=(R/'release-install'/relative).read_bytes():raise RuntimeError('Native release differs from staged bytes')
        for destination in [ROOT/relative,SNAP/relative]:same_copy(p,destination)
        records.append(dict(path=relative,E_native_G_equal=True,bytes=p.stat().st_size))
    same_copy(src/'reports/submission/w-release-20261104/native-activation.json',R/'native-activation.json')
    for name in ['ffn_cp_C16','ffn_lp_IR']:
        p=ROOT/'constraints/submission'/(name+'.json')
        if p.read_bytes()!=(R/'release-install/constraints/submission'/(name+'.json')).read_bytes():raise RuntimeError('Rollback bytes changed')
    index=Path('G:/xpian_历史版本库/00_总索引与公共参数')
    for relative in native['installed']:
        if relative.startswith('constraints/submission/'):
            target=index/'当前选择与固定条件/回退与发布配置'/Path(relative).name
        elif relative in ['constraints/ffn_selected.json','constraints/ffn_next_objective.json']:
            target=index/'当前选择与固定条件'/Path(relative).name
        elif relative=='constraints/ffn_submission_priority.json' or relative=='docs/ffn-submission-priority.md':
            target=index/'提交优先级'/relative
        else:continue
        if target.exists():same_copy(target,R/'before-G-index'/target.relative_to(index))
        same_copy(ROOT/relative,target)
    readme=Path('G:/xpian_历史版本库/README.md');same_copy(readme,R/'before-G-index/README.md')
    text=readme.read_text(encoding='utf-8')+'\n## 2026-11-04当前执行发布版（最新）\n\n当前发布为`ffn_ce_W`，独立完整快照位于`提交版本/V003_ffn_ce_W`。W：1514.9066817484043tasks/s、18.22518977709749μJ/任务、27.609461769457697mW、0.252858163mm²。C16与IR保留回退，原V002/V001目录及历史成绩不改写。本次按用户授权切换当前执行配置，正式综合计分的候选排序仍独立保留。\n'
    readme.write_text(text,encoding='utf-8')
    row=load(ROOT/'constraints/ffn_selected.json')['measured'];profile=load(ROOT/'constraints/ffn_selected.json')['implementation']
    completion=dict(complete=True,variant='ffn_ce_W',previous_variant='ffn_cp_C16',fallbacks=['ffn_cp_C16','ffn_lp_IR'],
        time=datetime.now(timezone(timedelta(hours=8))).isoformat(),published_configuration='constraints/ffn_selected.json',implementation=profile,
        verified_local_archive=True,verified_g_archive=True,native_activation_confirmed=True,selected_three_locations_byte_equal=True,
        fallback_configurations=['constraints/submission/ffn_cp_C16.json','constraints/submission/ffn_lp_IR.json'],fallback_bytes_preserved=True,
        accepted_CPU_SAIF_PPA_proofs_reused=True,representative_real_cpu_mapped_passed=True,same_final_netlist_ss150mhz_passed=True,
        g_release_directory=str(G),submission_order_changed=False,throughput_per_second=row['throughput_per_second'],mean_energy_j=row['mean_energy_j'],
        mean_power_w=row['mean_power_w'],scoring_area_mm2=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'])
    write(R/'completion.json',completion);write(R/'three-location-comparison.json',dict(complete=True,entries=records,selected_installed_last=True,fallback_bytes_preserved=True))
    write(R/'release-parameters.json',dict(version='V003_ffn_ce_W',current_execution_release='ffn_ce_W',fallbacks=['ffn_cp_C16','ffn_lp_IR'],
        precision='Q2/int16 effective36 exact RNE/saturation',MACs=32,clock_hz=150000000,corner='frozen SS 0.99V125C OCV/EMA2',
        cycles=row['cycles'],throughput_tasks_per_second=row['throughput_per_second'],mean_energy_j=row['mean_energy_j'],mean_power_w=row['mean_power_w'],
        scoring_area_mm2=completion['scoring_area_mm2'],implementation_tag=profile['tag'],source_snapshot='build/optimization/rtl_sources/ffn_ce_W',
        firmware='build/optimization/firmware/ffn_ce_W',acceptance=completion))
    for p in R.rglob('*'):
        if p.is_file():
            for base in [SNAP/'reports/submission/w-release-20261104',G/'发布记录']:same_copy(p,base/p.relative_to(R))
    same_copy(R/'release-parameters.json',G/'version-parameters.json');same_copy(R/'completion.json',G/'completion.json')
    print('W_RELEASE_E_NATIVE_G_IDENTICAL',len(records),completion['variant'],completion['fallbacks'],flush=True)

if __name__=='__main__':main()
