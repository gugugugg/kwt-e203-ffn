"""Stage the explicitly authorized W execution release and keep C16/IR rollback bytes."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import gzip,json,shutil,tarfile

ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/'reports/submission/w-release-20261104'
EXP=ROOT/'reports/optimization/ffn_c16_efficiency'
STAGE=REPORT/'release-install'
G=Path('G:/xpian_历史版本库/提交版本/V003_ffn_ce_W')

def load(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')

def main():
    old=load(ROOT/'constraints/ffn_selected.json')
    ack=load(EXP/'local-sync-confirmed.json');audit=load(EXP/'final-acceptance-audit.json')
    closing=load(EXP/'closing-native-receipt.json');row=load(EXP/'ffn_ce_W.json')
    profile=load(ROOT/row['profile'])
    if old['variant']!='ffn_cp_C16' or not all([ack['native_ack_confirmed'],ack['verified_local_archive'],ack['verified_G_archive'],audit['passed'],closing['complete']]):
        raise RuntimeError('Read the current C16 release and complete W native/E/G evidence')
    if not all(row.get(k) for k in ['formal_passed','mapped_passed','rtl_formal_passed','hold_repair_formal_passed','final_repair_formal_passed']):raise RuntimeError('W acceptance is incomplete')
    before=REPORT/'before-activation'
    paths=['AGENTS.md','constraints/ffn_selected.json','constraints/ffn_submission_priority.json','constraints/ffn_next_objective.json','docs/ffn-submission-priority.md','docs/ffn-next-objective.md']
    for relative in paths:
        p=ROOT/relative;t=before/relative;t.parent.mkdir(parents=True,exist_ok=True)
        if t.exists() and t.read_bytes()!=p.read_bytes():raise RuntimeError('Read the existing release preparation')
        shutil.copyfile(str(p),str(t))
    if (ROOT/'constraints/submission/ffn_cp_C16.json').read_bytes()!=(ROOT/'constraints/ffn_selected.json').read_bytes():raise RuntimeError('C16 rollback does not equal the prior publication')
    now=datetime.now(timezone(timedelta(hours=8))).isoformat()
    fallbacks=['constraints/submission/ffn_cp_C16.json','constraints/submission/ffn_lp_IR.json']
    config=load(ROOT/'build/optimization/complete_soc/ffn_ce_W/configuration.json')
    config.update(implementation=profile,measured=row,numerical_package=old['numerical_package'],submission_readiness='ready',
        evidence_source='reports/optimization/ffn_c16_efficiency/ffn_ce_W.json',acceptance=old['acceptance'],
        objective=['user_requested_published_execution','accepted_W_energy_area_throughput'],
        compute_mac_count=32,compute_rows=2,compute_columns=16,physical_weight_banks=16,
        release=dict(published_variant='ffn_ce_W',previous_published_variant='ffn_cp_C16',authorized_at=now,
            activation_record='reports/submission/w-release-20261104/native-activation.json',
            complete_evidence='reports/optimization/ffn_c16_efficiency/closing-native-receipt.json',
            fallback_configuration=fallbacks[0],fallback_configurations=fallbacks,
            representative_mapped='reports/optimization/complete_soc/ffn_ce_W/mapped_evaluation.json',g_snapshot=str(G/'工程快照')))
    write(STAGE/'constraints/ffn_selected.json',config);write(STAGE/'constraints/submission/ffn_ce_W.json',config)
    for relative in fallbacks:
        target=STAGE/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(str(ROOT/relative),str(target))
    priority=load(ROOT/'constraints/ffn_submission_priority.json')
    priority.update(updated_at=now,published_execution_variant='ffn_ce_W',previous_published_execution_variant='ffn_cp_C16',release_activation_record='reports/submission/w-release-20261104/native-activation.json')
    priority['execution_release']=dict(variant='ffn_ce_W',fallback='ffn_cp_C16',fallbacks=['ffn_cp_C16','ffn_lp_IR'],user_requested=True,submission_order_changed=False,submission_comparison='Retain IR, C16 and W; this authorization changes execution publication')
    additional=priority.get('additional_accepted_candidates',[])
    for item in additional:
        if item['variant']=='ffn_cp_C16':item['role']='execution_rollback_candidate'
    additional=[x for x in additional if x['variant']!='ffn_ce_W']
    additional.insert(0,dict(variant='ffn_ce_W',role='published_execution_candidate',submission_priority=None,
        throughput_tasks_per_second=row['throughput_per_second'],weighted_mean_power_w=row['mean_power_w'],mean_energy_j=row['mean_energy_j'],
        scoring_area_mm2=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'],final_implementation_profile=row['profile'],representative_mapped_passed=True,submission_readiness='ready'))
    priority['additional_accepted_candidates']=additional;priority['active_experiment']['status']='completed'
    write(STAGE/'constraints/ffn_submission_priority.json',priority)
    objective=load(ROOT/'constraints/ffn_next_objective.json')
    objective.update(status='completed_W_explicitly_published',updated_at=now,current_execution_release='ffn_ce_W',fallbacks=['ffn_cp_C16','ffn_lp_IR'],release_record='reports/submission/w-release-20261104/native-activation.json')
    objective['joint_target']['release']='Explicitly authorized W release; C16 and IR rollback. The completed experiment reference remains C16.'
    write(STAGE/'constraints/ffn_next_objective.json',objective)
    announcement='- Publication update 2026-11-04 (latest): the user explicitly authorized fully accepted ffn_ce_W as the current execution release. Retain exact ffn_cp_C16 and ffn_lp_IR rollback configurations and all historical evidence. W: 99016 cycles, 1514.9066817484043 tasks/s, 1.822518977709749e-05 J/task, 0.027609461769457697 W, 0.252858163 mm2. This supersedes older C16-remains-published statements for current execution; no new experiment or automatic submission-score reordering is authorized.\n\n'
    agents=(ROOT/'AGENTS.md').read_text(encoding='utf-8')
    (STAGE/'AGENTS.md').write_text(agents.replace('# Project workspace\n\n','# Project workspace\n\n'+announcement,1),encoding='utf-8')
    for relative in ['docs/ffn-submission-priority.md','docs/ffn-next-objective.md']:
        text=(ROOT/relative).read_text(encoding='utf-8')
        text+='\n## 2026-11-04用户明确授权发布W（最新执行状态）\n\n当前执行发布版为`ffn_ce_W`。C16和IR原配置分别保留于`constraints/submission/ffn_cp_C16.json`、`constraints/submission/ffn_lp_IR.json`，字节不改。自身全部平台验收及E/G归档/native ACK已完成，未重跑成功CPU/PPA或更改历史成绩。W：99016周期、1514.9066817484043tasks/s、18.22518977709749μJ/任务、27.609461769457697mW、0.252858163mm²。发布记录`reports/submission/w-release-20261104`；G盘`提交版本/V003_ffn_ce_W`。\n\n本次只按授权切换当前发布配置，保留正式计分比较候选及既有提交排序；此前“保持C16发布”是此次授权前的状态。固定实验参照和数值阈值仍保留，不启动新实验。\n'
        p=STAGE/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    archive=EXP/'received/final/native-accepted-archive.tar.gz';destination=G/'工程快照';count=0
    with archive.open('rb') as raw,gzip.GzipFile(fileobj=raw,mode='rb') as decoded,tarfile.open(fileobj=decoded,mode='r|') as stream:
        for member in stream:
            if not member.isfile():continue
            value=stream.extractfile(member).read();p=destination/member.name;p.parent.mkdir(parents=True,exist_ok=True)
            if not p.exists() or p.read_bytes()!=value:p.write_bytes(value)
            if p.read_bytes()!=value:raise RuntimeError('W G snapshot differs '+member.name)
            count+=1
    extra=load(EXP/'closing-local-comparison.json')['entries']
    extras=[ROOT/e['path'] for e in extra]+[EXP/'closing-native-receipt.json',EXP/'closing-local-comparison.json']
    for p in extras:
        t=destination/p.relative_to(ROOT);t.parent.mkdir(parents=True,exist_ok=True);t.write_bytes(p.read_bytes())
        if t.read_bytes()!=p.read_bytes():raise RuntimeError('W closing evidence G bytes differ')
    staged=sorted(p for p in STAGE.rglob('*') if p.is_file() and p!=STAGE/'constraints/ffn_selected.json')+[STAGE/'constraints/ffn_selected.json']
    for p in staged:
        t=destination/p.relative_to(STAGE);t.parent.mkdir(parents=True,exist_ok=True);t.write_bytes(p.read_bytes())
        if t.read_bytes()!=p.read_bytes():raise RuntimeError('Staged G release bytes differ')
    shutil.copyfile(str(archive),str(G/'native-accepted-archive.tar.gz'))
    if archive.read_bytes()!=(G/'native-accepted-archive.tar.gz').read_bytes():raise RuntimeError('W G accepted archive differs')
    sync=dict(variant='ffn_ce_W',previous_variant='ffn_cp_C16',fallbacks=['ffn_cp_C16','ffn_lp_IR'],verified_local_archive=True,verified_g_archive=True,
        full_archive_bytes=ack['bytes'],full_archive_crc32=ack['crc32'],original_archive_files=count,g_release_directory=str(G),g_engineering_snapshot=str(destination),
        staged_files=[p.relative_to(STAGE).as_posix() for p in staged],native_activation_pending=True,time=now)
    write(STAGE/'sync-before-activation.json',sync);write(REPORT/'preparation.json',sync)
    print('W_RELEASE_STAGED_G_COMPARED',count,len(staged),flush=True)

if __name__=='__main__':main()
