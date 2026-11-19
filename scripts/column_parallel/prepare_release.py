"""Stage the user-requested C16 publication using its completed platform evidence."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import gzip
import json
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT/'reports/submission/c16-release-20261104'
EXPERIMENT = ROOT/'reports/optimization/ffn_column_parallel'
STAGE = REPORT/'release-install'
G = Path('G:/xpian_历史版本库/提交版本/V002_ffn_cp_C16')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def main():
    selected = load(ROOT/'constraints/ffn_selected.json')
    if selected['variant'] != 'ffn_lp_IR':
        raise RuntimeError('Read the actual published configuration before staging')
    completed = load(EXPERIMENT/'completion.json')
    ack = load(EXPERIMENT/'local-sync-confirmed.json')
    row = load(EXPERIMENT/'ffn_cp_C16.json')
    profile = load(ROOT/row['profile'])
    if not (completed['complete'] and completed['native_ack_confirmed'] and ack['verified_local_archive'] and ack['verified_G_archive']):
        raise RuntimeError('C16 native/E/G delivery is incomplete')
    if not all(row.get(k) for k in ['formal_passed', 'mapped_passed', 'rtl_formal_passed', 'hold_repair_formal_passed', 'final_repair_formal_passed']):
        raise RuntimeError('Read completed own C16 acceptance')
    before = REPORT/'before-activation'
    paths = ['AGENTS.md', 'constraints/ffn_selected.json', 'constraints/ffn_submission_priority.json', 'docs/ffn-submission-priority.md']
    for relative in paths:
        target = before/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != (ROOT/relative).read_bytes():
            raise RuntimeError('Read the previous publication staging receipt')
        shutil.copyfile(str(ROOT/relative), str(target))
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    config = load(ROOT/'build/optimization/complete_soc/ffn_cp_C16/configuration.json')
    config.update(implementation=profile, measured=row, numerical_package=selected['numerical_package'],
                  submission_readiness='ready', evidence_source='reports/optimization/ffn_column_parallel/ffn_cp_C16.json',
                  acceptance=selected['acceptance'], objective=['user_requested_published_execution', 'accepted_C16_energy_area_throughput'],
                  compute_mac_count=32, compute_rows=2, compute_columns=16, physical_weight_banks=16,
                  release=dict(published_variant='ffn_cp_C16', previous_published_variant='ffn_lp_IR', authorized_at=now,
                               activation_record='reports/submission/c16-release-20261104/native-activation.json',
                               complete_evidence='reports/optimization/ffn_column_parallel/completion.json',
                               fallback_configuration='constraints/submission/ffn_lp_IR.json',
                               representative_mapped='reports/optimization/complete_soc/ffn_cp_C16/mapped_evaluation.json',
                               g_snapshot=str(G/'工程快照')))
    write(STAGE/'constraints/ffn_selected.json', config)
    write(STAGE/'constraints/submission/ffn_cp_C16.json', config)
    fallback = STAGE/'constraints/submission/ffn_lp_IR.json'
    shutil.copyfile(str(ROOT/'constraints/submission/ffn_lp_IR.json'), str(fallback))
    priority = load(ROOT/'constraints/ffn_submission_priority.json')
    priority.update(updated_at=now, published_execution_variant='ffn_cp_C16',
                    previous_published_execution_variant='ffn_lp_IR',
                    release_activation_record='reports/submission/c16-release-20261104/native-activation.json')
    priority['execution_release'] = dict(variant='ffn_cp_C16', fallback='ffn_lp_IR', user_requested=True,
                                         submission_order_changed=False, submission_comparison='Retain IR and C16 pending official common-group references')
    priority['additional_accepted_candidates'] = [dict(variant='ffn_cp_C16', role='published_execution_candidate',
        submission_priority=None, throughput_tasks_per_second=row['throughput_per_second'],
        weighted_mean_power_w=row['mean_power_w'], mean_energy_j=row['mean_energy_j'],
        scoring_area_mm2=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'],
        final_implementation_profile=row['profile'], representative_mapped_passed=True, submission_readiness='ready')]
    priority['active_experiment']['status'] = 'completed'
    write(STAGE/'constraints/ffn_submission_priority.json', priority)
    agents = (ROOT/'AGENTS.md').read_text(encoding='utf-8')
    announcement = '- Publication update 2026-11-04: the user explicitly authorized replacing the published configuration with fully accepted ffn_cp_C16. Current execution release is C16; retain IR as the rollback configuration and preserve all historical acceptance/release evidence. This supersedes older IR-remains-published statements for current execution only; it does not claim an official-score ranking or authorize another experiment.\n\n'
    (STAGE/'AGENTS.md').parent.mkdir(parents=True, exist_ok=True)
    (STAGE/'AGENTS.md').write_text(agents.replace('# Project workspace\n\n', '# Project workspace\n\n'+announcement, 1), encoding='utf-8')
    doc = (ROOT/'docs/ffn-submission-priority.md').read_text(encoding='utf-8')
    doc += '\n## 2026-11-04用户授权发布C16\n\n当前执行发布配置切换为`ffn_cp_C16`，IR完整配置保留于`constraints/submission/ffn_lp_IR.json`作为回退。C16已完成真实CPU12/SAIF、同最终网表正式SS150MHz/门控/电气、原生功耗12项、三段证明和代表真实CPU mapped，以及E/G逐文件同步与native ACK。\n\nC16：1491.5429514651923tasks/s，18.435083907942435μJ/任务，0.253049045mm²，27.496719462560937mW。发布记录见`reports/submission/c16-release-20261104`；独立G盘版本目录为`提交版本/V002_ffn_cp_C16`。\n\n这次授权切换当前执行发布版；正式综合计分的提交排序仍保留IR/C16多个候选，未虚构同组参考值或改写历轮结果。此前“IR继续当前发布”描述为此次授权前的历史状态。\n'
    (STAGE/'docs').mkdir(exist_ok=True)
    (STAGE/'docs/ffn-submission-priority.md').write_text(doc, encoding='utf-8')
    archive = EXPERIMENT/'received/final/native-accepted-archive.tar.gz'
    destination = G/'工程快照'
    count = 0
    with archive.open('rb') as raw, gzip.GzipFile(fileobj=raw, mode='rb') as decoded, tarfile.open(fileobj=decoded, mode='r|') as stream:
        for member in stream:
            if not member.isfile():
                continue
            value = stream.extractfile(member).read()
            target = destination/member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != value:
                target.write_bytes(value)
            if target.read_bytes() != value:
                raise RuntimeError('G release snapshot differs: '+member.name)
            count += 1
    for path in STAGE.rglob('*'):
        if path.is_file():
            target = destination/path.relative_to(STAGE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
            if target.read_bytes() != path.read_bytes():
                raise RuntimeError('G staged release metadata differs')
    G.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(archive), str(G/'native-accepted-archive.tar.gz'))
    if archive.read_bytes() != (G/'native-accepted-archive.tar.gz').read_bytes():
        raise RuntimeError('G native archive differs')
    sync = dict(variant='ffn_cp_C16', previous_variant='ffn_lp_IR', verified_local_archive=True,
                verified_g_archive=True, full_archive_bytes=ack['bytes'], full_archive_crc32=ack['crc32'],
                original_archive_files=count, g_release_directory=str(G), g_engineering_snapshot=str(destination),
                staged_files=sorted(p.relative_to(STAGE).as_posix() for p in STAGE.rglob('*') if p.is_file()),
                native_activation_pending=True, time=now)
    write(STAGE/'sync-before-activation.json', sync)
    write(REPORT/'preparation.json', sync)
    print('C16_RELEASE_STAGED_G_COMPARED', count, len(sync['staged_files']), flush=True)


if __name__ == '__main__':
    main()
