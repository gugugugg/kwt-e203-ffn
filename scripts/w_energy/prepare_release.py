"""Stage the requested C publication with byte-preserved W/C16/IR rollback."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import gzip,json,shutil,tarfile
ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/'reports/submission/wen-C-release-20261104'
EXP=ROOT/'reports/optimization/ffn_w_energy';STAGE=REPORT/'release-install'
G=Path('G:/xpian_历史版本库/提交版本/V004_ffn_wen_C')
FALLBACKS=['ffn_ce_W','ffn_cp_C16','ffn_lp_IR']
def load(p):return json.loads(p.read_text(encoding='utf8'))
def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf8')
def copy(p,q):
    q.parent.mkdir(parents=True,exist_ok=True);data=p.read_bytes()
    if not q.exists() or q.read_bytes()!=data:q.write_bytes(data)
    if q.read_bytes()!=data:raise RuntimeError('Release copy differs '+str(q))
def main():
    old=load(ROOT/'constraints/ffn_selected.json');row=load(EXP/'ffn_wen_C.json');profile=load(ROOT/row['profile'])
    ack=load(EXP/'local-sync-confirmed.json');audit=load(EXP/'final-acceptance-audit.json');closing=load(EXP/'closing-native-receipt.json')
    if old['variant']!='ffn_ce_W' or not all([ack['verified_local_archive'],ack['verified_G_archive'],ack['native_ack_confirmed'],audit['passed'],closing['complete']]):raise RuntimeError('Read current W and completed C acceptance/sync')
    if not all(row.get(k) for k in ['formal_passed','mapped_passed','rtl_formal_passed','hold_repair_formal_passed','final_repair_formal_passed']):raise RuntimeError('Read complete C final acceptance')
    if (ROOT/'constraints/submission/ffn_ce_W.json').read_bytes()!=(ROOT/'constraints/ffn_selected.json').read_bytes():raise RuntimeError('W rollback differs from current release')
    paths=['AGENTS.md','constraints/ffn_selected.json','constraints/ffn_submission_priority.json','constraints/ffn_next_objective.json','docs/ffn-submission-priority.md','docs/ffn-next-objective.md']+['constraints/submission/'+name+'.json' for name in FALLBACKS]
    for name in paths:
        p=ROOT/name;q=REPORT/'before-activation'/name
        if q.exists() and q.read_bytes()!=p.read_bytes():raise RuntimeError('Read existing release preparation')
        copy(p,q)
    now=datetime.now(timezone(timedelta(hours=8))).isoformat();fallback_paths=['constraints/submission/'+name+'.json' for name in FALLBACKS]
    config=load(ROOT/'build/optimization/complete_soc/ffn_wen_C/configuration.json')
    config.update(implementation=profile,measured=row,numerical_package=old['numerical_package'],submission_readiness='ready',
        evidence_source='reports/optimization/ffn_w_energy/ffn_wen_C.json',acceptance=old['acceptance'],
        objective=['user_requested_published_execution','accepted_C_energy_area_throughput'],compute_mac_count=32,compute_rows=2,compute_columns=16,physical_weight_banks=16,
        release=dict(published_variant='ffn_wen_C',previous_published_variant='ffn_ce_W',authorized_at=now,
            activation_record='reports/submission/wen-C-release-20261104/native-activation.json',complete_evidence='reports/optimization/ffn_w_energy/closing-native-receipt.json',
            fallback_configuration=fallback_paths[0],fallback_configurations=fallback_paths,representative_mapped='reports/optimization/complete_soc/ffn_wen_C/mapped_evaluation.json',g_snapshot=str(G/'工程快照')))
    write(STAGE/'constraints/ffn_selected.json',config);write(STAGE/'constraints/submission/ffn_wen_C.json',config)
    for name in fallback_paths:copy(ROOT/name,STAGE/name)
    priority=load(ROOT/'constraints/ffn_submission_priority.json')
    priority.update(updated_at=now,published_execution_variant='ffn_wen_C',previous_published_execution_variant='ffn_ce_W',release_activation_record='reports/submission/wen-C-release-20261104/native-activation.json')
    priority['execution_release']=dict(variant='ffn_wen_C',fallback='ffn_ce_W',fallbacks=FALLBACKS,user_requested=True,submission_order_changed=False,submission_comparison='Preserve official-score candidates and prior submission order; update current execution release')
    additional=[x for x in priority.get('additional_accepted_candidates',[]) if x['variant']!='ffn_wen_C']
    for item in additional:
        if item['variant'] in FALLBACKS:item['role']='execution_rollback_candidate'
    additional.insert(0,dict(variant='ffn_wen_C',role='published_execution_candidate',submission_priority=None,throughput_tasks_per_second=row['throughput_per_second'],weighted_mean_power_w=row['mean_power_w'],mean_energy_j=row['mean_energy_j'],scoring_area_mm2=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'],final_implementation_profile=row['profile'],representative_mapped_passed=True,submission_readiness='ready'))
    priority['additional_accepted_candidates']=additional;priority['active_experiment']['status']='completed';write(STAGE/'constraints/ffn_submission_priority.json',priority)
    objective=load(ROOT/'constraints/ffn_next_objective.json');objective.update(status='completed_C_explicitly_published',updated_at=now,current_execution_release='ffn_wen_C',fallbacks=FALLBACKS,release_record='reports/submission/wen-C-release-20261104/native-activation.json')
    objective['joint_target']['release']='Explicitly authorized C publication; W/C16/IR rollback; completed experiment reference and thresholds remain W.'
    objective['selection_order']=['Completed same-precision platform acceptance','E<W, A<=0.2764843225, T>=1000','E then T then A; retain independent official-score candidates']
    write(STAGE/'constraints/ffn_next_objective.json',objective)
    announcement='- Publication update 2026-11-04 (latest): the user explicitly authorized fully accepted ffn_wen_C as the current execution release. Preserve exact ffn_ce_W, ffn_cp_C16 and ffn_lp_IR rollback configurations and their independent prior releases. C: 98783 cycles, 1518.4799003877185 tasks/s, 1.8076843983968133e-05 J/task, 0.027449324252100258 W, 0.252275623 mm2. This supersedes prior W-remains-published statements for current execution; reuse accepted CPU/SAIF/STA/power/proofs/mapped and do not start a new experiment.\n\n'
    agents=(ROOT/'AGENTS.md').read_text(encoding='utf8');(STAGE/'AGENTS.md').write_text(agents.replace('# Project workspace\n\n','# Project workspace\n\n'+announcement,1),encoding='utf8')
    note='\n## 2026-11-04用户明确授权发布C（最新执行状态）\n\n当前执行发布版为`ffn_wen_C`，W、C16、IR原配置分别保留于`constraints/submission/ffn_ce_W.json`、`ffn_cp_C16.json`、`ffn_lp_IR.json`，字节不改。C：98783周期、1518.4799003877185tasks/s、18.076843983968132μJ/任务、27.449324252100258mW、0.252275623mm²，自身完整验收/代表mapped/E-G同步/native ACK均已完成。发布记录`reports/submission/wen-C-release-20261104`，G盘独立版本`提交版本/V004_ffn_wen_C`。旧发布W/C16/IR和所有研究档案保留，未重跑成功硬件阶段。既有正式综合计分候选与提交排序独立保留，完成实验的W固定参照和数值阈值不移动。\n'
    for name in ['docs/ffn-submission-priority.md','docs/ffn-next-objective.md']:
        p=STAGE/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text((ROOT/name).read_text(encoding='utf8')+note,encoding='utf8')
    destination=G/'工程快照';archive=EXP/'received/final/native-accepted-archive.tar.gz';count=0
    with archive.open('rb') as raw,gzip.GzipFile(fileobj=raw,mode='rb') as decoded,tarfile.open(fileobj=decoded,mode='r|') as stream:
        for m in stream:
            if not m.isfile():continue
            value=stream.extractfile(m).read();p=destination/m.name;p.parent.mkdir(parents=True,exist_ok=True)
            if not p.exists() or p.read_bytes()!=value:p.write_bytes(value)
            if p.read_bytes()!=value:raise RuntimeError('C G engineering snapshot differs '+m.name)
            count+=1
            if count%1000==0:print('C_RELEASE_G_SNAPSHOT_FILES',count,flush=True)
    extra=['final-selection.json','delivery-status.json','local-sync-confirmed.json','local-archive-comparison.json','native-archive-manifest.json','closing-native-receipt.json','final-acceptance-audit.json','version-parameters.json','conclusion.md','current-state.md']
    for name in extra:copy(EXP/name,destination/'reports/optimization/ffn_w_energy'/name)
    copy(ROOT/'constraints/ffn_w_energy/selected.json',destination/'constraints/ffn_w_energy/selected.json')
    for name in load(EXP/'deployment/w-energy-closing.json')['files']:copy(ROOT/name,destination/name)
    staged=sorted(p for p in STAGE.rglob('*') if p.is_file() and p!=STAGE/'constraints/ffn_selected.json')+[STAGE/'constraints/ffn_selected.json']
    for p in staged:copy(p,destination/p.relative_to(STAGE))
    copy(archive,G/'native-accepted-archive.tar.gz')
    sync=dict(variant='ffn_wen_C',previous_variant='ffn_ce_W',fallbacks=FALLBACKS,verified_local_archive=True,verified_g_archive=True,full_archive_bytes=ack['bytes'],full_archive_crc32=ack['crc32'],original_archive_files=count,g_release_directory=str(G),g_engineering_snapshot=str(destination),staged_files=[p.relative_to(STAGE).as_posix() for p in staged],native_activation_pending=True,time=now)
    write(STAGE/'sync-before-activation.json',sync);write(REPORT/'preparation.json',sync);print('C_RELEASE_STAGED_G_COMPARED',count,len(staged),flush=True)
if __name__=='__main__':main()
