"""Install native-confirmed C and update the G release index and parameters."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json
from prepare_release import ROOT,REPORT,EXP,STAGE,G,FALLBACKS,load,write,copy
def main():
    src=EXP/'received/C-release-activation/native-evidence';native=load(src/'reports/submission/wen-C-release-20261104/native-activation.json');snap=G/'工程快照'
    if not native['complete'] or not native['selected_installed_last'] or native['variant']!='ffn_wen_C':raise RuntimeError('Native C activation incomplete')
    records=[]
    for rel in native['installed']:
        p=src/rel
        if p.read_bytes()!=(STAGE/rel).read_bytes():raise RuntimeError('Native release differs from staged bytes')
        for base in [ROOT,snap]:
            target=base/rel
            if rel=='constraints/ffn_selected.json':
                temp=target.with_name(target.name+'.wen-C-release.tmp');temp.write_bytes(p.read_bytes());temp.replace(target)
                if target.read_bytes()!=p.read_bytes():raise RuntimeError('Published C bytes differ')
            else:copy(p,target)
        records.append(dict(path=rel,E_native_G_equal=True,bytes=p.stat().st_size))
    copy(src/'reports/submission/wen-C-release-20261104/native-activation.json',REPORT/'native-activation.json')
    for name in FALLBACKS:
        rel='constraints/submission/'+name+'.json'
        if (ROOT/rel).read_bytes()!=(REPORT/'before-activation'/rel).read_bytes():raise RuntimeError('Rollback changed '+name)
    index=Path('G:/xpian_历史版本库/00_总索引与公共参数')
    for rel in native['installed']:
        if rel.startswith('constraints/submission/'):target=index/'当前选择与固定条件/回退与发布配置'/Path(rel).name
        elif rel in ['constraints/ffn_selected.json','constraints/ffn_next_objective.json']:target=index/'当前选择与固定条件'/Path(rel).name
        elif rel in ['constraints/ffn_submission_priority.json','docs/ffn-submission-priority.md']:target=index/'提交优先级'/rel
        else:continue
        if target.exists():copy(target,REPORT/'before-G-index'/target.relative_to(index))
        copy(ROOT/rel,target)
    readme=Path('G:/xpian_历史版本库/README.md');copy(readme,REPORT/'before-G-index/README.md')
    text=readme.read_text(encoding='utf8')+'\n## 2026-11-04当前执行发布C（最新）\n\n当前发布为`ffn_wen_C`，独立工程快照位于`提交版本/V004_ffn_wen_C`。C：1518.4799003877185tasks/s、18.076843983968132μJ/任务、27.449324252100258mW、0.252275623mm²。W、C16、IR保留回退，原V003/V002/V001目录及历史成绩保持。\n'
    readme.write_text(text,encoding='utf8')
    config=load(ROOT/'constraints/ffn_selected.json');row=config['measured'];profile=config['implementation']
    completion=dict(complete=True,variant='ffn_wen_C',previous_variant='ffn_ce_W',fallbacks=FALLBACKS,time=datetime.now(timezone(timedelta(hours=8))).isoformat(),published_configuration='constraints/ffn_selected.json',implementation=profile,
        verified_local_archive=True,verified_g_archive=True,native_activation_confirmed=True,selected_three_locations_byte_equal=True,fallback_bytes_preserved=True,fallback_configurations=['constraints/submission/'+name+'.json' for name in FALLBACKS],accepted_CPU_SAIF_PPA_proofs_reused=True,representative_real_cpu_mapped_passed=True,same_final_netlist_ss150mhz_passed=True,g_release_directory=str(G),submission_order_changed=False,throughput_per_second=row['throughput_per_second'],mean_energy_j=row['mean_energy_j'],mean_power_w=row['mean_power_w'],scoring_area_mm2=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'])
    write(REPORT/'completion.json',completion);write(REPORT/'three-location-comparison.json',dict(complete=True,entries=records,selected_installed_last=True,fallback_bytes_preserved=True))
    write(REPORT/'release-parameters.json',dict(version='V004_ffn_wen_C',current_execution_release='ffn_wen_C',fallbacks=FALLBACKS,precision='Q2/int16 effective36 exact RNE/saturation',MACs=32,clock_hz=150000000,corner='frozen SS0.99V125C OCV/EMA2',cycles=row['cycles'],throughput_tasks_per_second=row['throughput_per_second'],mean_energy_j=row['mean_energy_j'],mean_power_w=row['mean_power_w'],scoring_area_mm2=completion['scoring_area_mm2'],implementation_tag=profile['tag'],source_snapshot=config['source_snapshot'],firmware=config['firmware'],acceptance=completion))
    for p in REPORT.rglob('*'):
        if p.is_file():
            for base in [snap/'reports/submission/wen-C-release-20261104',G/'发布记录']:copy(p,base/p.relative_to(REPORT))
    copy(REPORT/'release-parameters.json',G/'version-parameters.json');copy(REPORT/'completion.json',G/'completion.json')
    print('C_RELEASE_E_NATIVE_G_IDENTICAL',len(records),completion['variant'],FALLBACKS,flush=True)
if __name__=='__main__':main()
