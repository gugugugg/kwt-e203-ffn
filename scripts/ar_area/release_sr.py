"""Stage SR publication and reconcile native, E-drive and G-drive release files."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import gzip
import json
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ar_area'))
from package_files import package

RELEASE = 'reports/submission/ara-SR-release-20261105'
REPORT = ROOT / RELEASE
STAGE = REPORT / 'release-install'
EXP = ROOT / 'reports/optimization/ffn_ar_area'
LIBRARY = Path('G:/xpian_历史版本库')
G = LIBRARY / '提交版本/V006_ffn_ara_SR'
SNAPSHOT = G / '工程快照'
SR, AR = 'ffn_ara_SR', 'ffn_car_AR'
FALLBACKS = [AR, 'ffn_wen_C', 'ffn_ce_W', 'ffn_cp_C16', 'ffn_lp_IR']
SELECTED = 'constraints/ffn_selected.json'
PRIORITY = 'constraints/ffn_submission_priority.json'
OBJECTIVE = 'constraints/ffn_next_objective.json'
DOCS = ['docs/ffn-submission-priority.md', 'docs/ffn-next-objective.md']
FALLBACK_PATHS = ['constraints/submission/' + name + '.json' for name in FALLBACKS]
CURRENT_SR = 'constraints/submission/' + SR + '.json'
FILES = ['AGENTS.md', PRIORITY, OBJECTIVE] + DOCS + FALLBACK_PATHS + [CURRENT_SR, SELECTED]


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    value = src.read_bytes()
    if not dst.exists() or dst.read_bytes() != value:
        dst.write_bytes(value)
    if dst.read_bytes() != value:
        raise RuntimeError('Release bytes differ: ' + str(dst))


def install(src, dst):
    temporary = dst.with_name(dst.name + '.SR-release.tmp')
    copy(src, temporary)
    temporary.replace(dst)


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def prepare():
    previous = load(ROOT / SELECTED)
    row = load(EXP / (SR + '.json'))
    profile = load(ROOT / row['profile'])
    ack = load(EXP / 'local-sync-confirmed.json')
    audit = load(EXP / 'final-acceptance-audit.json')
    closing = load(EXP / 'closing-native-receipt.json')
    if previous['variant'] != AR or (ROOT / SELECTED).read_bytes() != (ROOT / FALLBACK_PATHS[0]).read_bytes():
        raise RuntimeError('Expected current AR and its exact rollback configuration')
    if not (ack['native_ack_confirmed'] and ack['verified_G_archive'] and closing['complete']
            and audit['passed'] and load(EXP / 'final-selection.json')['recommended_area_candidate'] == SR
            and row['objective_met'] and row['energy_not_increased']
            and row['formal_passed'] and row['mapped_passed']):
        raise RuntimeError('Read full SR acceptance and sync evidence')
    for rel in FILES:
        if (ROOT / rel).exists():
            copy(ROOT / rel, REPORT / 'before-activation' / rel)
    config = load(ROOT / 'build/optimization/complete_soc/ffn_ara_SR/configuration.json')
    config.update(implementation=profile, measured=row, numerical_package=previous['numerical_package'],
                  acceptance=previous['acceptance'], submission_readiness='ready',
                  evidence_source='reports/optimization/ffn_ar_area/ffn_ara_SR.json',
                  objective=['user_requested_published_execution', 'accepted_SR_area_energy_throughput'],
                  compute_mac_count=32, compute_rows=2, compute_columns=16, physical_weight_banks=16,
                  release=dict(published_variant=SR, previous_published_variant=AR, authorized_at=now(),
                               activation_record=RELEASE + '/native-activation.json',
                               complete_evidence='reports/optimization/ffn_ar_area/closing-native-receipt.json',
                               fallback_configuration=FALLBACK_PATHS[0], fallback_configurations=FALLBACK_PATHS,
                               representative_mapped='reports/optimization/complete_soc/ffn_ara_SR/mapped_evaluation.json',
                               g_snapshot=str(SNAPSHOT)))
    for rel in (SELECTED, CURRENT_SR):
        write(STAGE / rel, config)
    for rel in FALLBACK_PATHS:
        copy(ROOT / rel, STAGE / rel)

    priority = load(ROOT / PRIORITY)
    priority.update(updated_at=now(), published_execution_variant=SR, previous_published_execution_variant=AR,
                    release_activation_record=RELEASE + '/native-activation.json',
                    execution_release=dict(variant=SR, fallback=AR, fallbacks=FALLBACKS,
                                           user_requested=True, submission_order_changed=False))
    candidates = [item for item in priority['additional_accepted_candidates'] if item['variant'] != SR]
    for item in candidates:
        if item['variant'] in FALLBACKS:
            item['role'] = 'execution_rollback_candidate'
    candidates.insert(0, dict(variant=SR, role='published_execution_candidate', submission_priority=None,
                             throughput_tasks_per_second=row['throughput_per_second'],
                             weighted_mean_power_w=row['mean_power_w'], mean_energy_j=row['mean_energy_j'],
                             scoring_area_mm2=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'],
                             final_implementation_profile=row['profile'],
                             representative_mapped_passed=True, submission_readiness='ready'))
    priority['additional_accepted_candidates'] = candidates
    write(STAGE / PRIORITY, priority)

    objective = load(ROOT / OBJECTIVE)
    objective.update(status='completed_SR_explicitly_published', updated_at=now(), current_execution_release=SR,
                     fallbacks=FALLBACKS, release_record=RELEASE + '/native-activation.json')
    objective['joint_target']['release'] = 'SR execution release authorized by the user. AR, C, W, C16 and IR are rollbacks.'
    write(STAGE / OBJECTIVE, objective)

    note = ('\n## 2026-11-05 执行发布 SR\n\n'
            '当前执行发布版为 `ffn_ara_SR`，完整冷任务 98783 拍，1518.4799003877185 tasks/s，'
            '计分面积 0.250707394 mm²，任务能耗 17.990618656009402 μJ，平均功率 27.318392824690587 mW。'
            'AR、C、W、C16、IR 按该顺序作为执行回退，正式提交排序见优先级清单。\n')
    for rel in DOCS:
        path = STAGE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((ROOT / rel).read_text(encoding='utf-8') + note, encoding='utf-8')
    agents = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
    agents = agents.replace('Publication update 2026-11-05 (latest): the user selected fully accepted ffn_car_AR',
                            'Publication history 2026-11-05: the user selected fully accepted ffn_car_AR', 1)
    announcement = ('- Publication update 2026-11-05 (latest): the user selected fully accepted ffn_ara_SR '
                    'as current execution release. AR, C, W, C16 and IR are execution rollbacks in that order. '
                    'SR: 98783 cycles, 1518.4799003877185 tasks/s, 0.250707394 mm2, '
                    '1.7990618656009402e-05 J/task, 0.027318392824690587 W.\n\n')
    (STAGE / 'AGENTS.md').write_text(agents.replace('# Project workspace\n\n', '# Project workspace\n\n' + announcement, 1),
                                    encoding='utf-8')

    archive = EXP / 'received/final/native-accepted-archive.tar.gz'
    count = 0
    with gzip.open(archive, 'rb') as decoded, tarfile.open(fileobj=decoded, mode='r|') as stream:
        for member in stream:
            if not member.isfile():
                continue
            value = stream.extractfile(member).read()
            target = SNAPSHOT / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
            if target.read_bytes() != value:
                raise RuntimeError('G engineering snapshot differs: ' + member.name)
            count += 1
            if count % 1000 == 0:
                print('SR_RELEASE_G_FILES', count, flush=True)
    if count != ack['files'] or archive.stat().st_size != ack['bytes']:
        raise RuntimeError('Read original verified SR delivery archive')
    copy(archive, G / 'native-accepted-archive.tar.gz')
    for name in ['final-selection.json', 'delivery-status.json', 'local-sync-confirmed.json',
                 'native-archive-manifest.json', 'closing-native-receipt.json', 'final-acceptance-audit.json',
                 'version-parameters.json', 'completion.json', 'current-state.md', 'normal-power-activity-review.json']:
        copy(EXP / name, SNAPSHOT / 'reports/optimization/ffn_ar_area' / name)
    copy(ROOT / 'constraints/ffn_ar_area/selected.json', SNAPSHOT / 'constraints/ffn_ar_area/selected.json')
    for rel in FILES:
        copy(STAGE / rel, SNAPSHOT / rel)
    write(REPORT / 'preparation.json', dict(variant=SR, previous_variant=AR, fallbacks=FALLBACKS,
                                          archive=ack, g_archive_files=count, installed=FILES))
    paths = [RELEASE + '/release-install/' + rel for rel in FILES]
    paths += [RELEASE + '/before-activation/' + SELECTED, RELEASE + '/preparation.json',
              'scripts/ar_area/ara-SR-native.py', 'scripts/ar_area/release_sr.py']
    package('ara-SR-release-activation', paths)


def complete(label):
    received = EXP / 'received' / label / 'native-evidence'
    receipt = load(received / RELEASE / 'native-activation.json')
    if not receipt['complete'] or receipt['variant'] != SR or receipt['installed'] != FILES:
        raise RuntimeError('Read confirmed native SR activation')
    for rel in FILES:
        if (received / rel).read_bytes() != (STAGE / rel).read_bytes():
            raise RuntimeError('Native SR release bytes differ: ' + rel)
    index = LIBRARY / '00_总索引与公共参数'
    for rel in [PRIORITY, OBJECTIVE] + DOCS + FALLBACK_PATHS + [SELECTED]:
        destination = (index / '提交优先级' / rel if rel in DOCS[:1] or rel == PRIORITY else
                       index / '当前选择与固定条件' / Path(rel).name if rel in [SELECTED, OBJECTIVE] else
                       index / '当前选择与固定条件/回退与发布配置' / Path(rel).name if rel in FALLBACK_PATHS else None)
        if destination is not None and destination.exists():
            copy(destination, REPORT / 'before-G-index' / destination.relative_to(index))
    for rel in FILES:
        source = received / rel
        install(source, ROOT / rel)
        copy(source, SNAPSHOT / rel)
        if rel in DOCS[:1] or rel == PRIORITY:
            copy(source, index / '提交优先级' / rel)
        elif rel in [SELECTED, OBJECTIVE]:
            copy(source, index / '当前选择与固定条件' / Path(rel).name)
        elif rel in FALLBACK_PATHS + [CURRENT_SR]:
            copy(source, index / '当前选择与固定条件/回退与发布配置' / Path(rel).name)
    readme = LIBRARY / 'README.md'
    copy(readme, REPORT / 'before-G-index/README.md')
    with readme.open('a', encoding='utf-8') as stream:
        stream.write('\n## 2026-11-05 当前执行发布 SR\n\n'
                     '当前发布为 `ffn_ara_SR`，独立工程快照位于 `提交版本/V006_ffn_ara_SR`。'
                     'AR、C、W、C16、IR 依次作为执行回退。\n')
    copy(received / RELEASE / 'native-activation.json', REPORT / 'native-activation.json')
    config = load(ROOT / SELECTED)
    row = config['measured']
    completion = dict(complete=True, variant=SR, previous_variant=AR, fallbacks=FALLBACKS,
                      E_native_G_selection_identical=True, native_activation_confirmed=True,
                      verified_g_archive=True, g_release_directory=str(G), submission_order_changed=False,
                      implementation_tag=config['implementation']['tag'], cycles=row['cycles'],
                      throughput_tasks_per_second=row['throughput_per_second'], mean_energy_j=row['mean_energy_j'],
                      mean_power_w=row['mean_power_w'],
                      scoring_area_mm2=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'],
                      precision='Q2/int16 effective36 exact RNE/saturation', MACs=32, clock_hz=150000000,
                      acceptance=receipt)
    write(REPORT / 'completion.json', completion)
    copy(REPORT / 'completion.json', G / 'completion.json')
    copy(REPORT / 'completion.json', G / 'version-parameters.json')
    for path in REPORT.rglob('*'):
        if path.is_file():
            copy(path, G / '发布记录' / path.relative_to(REPORT))
    print('SR_RELEASE_E_NATIVE_G_IDENTICAL', len(FILES), flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'prepare':
        prepare()
    else:
        complete(sys.argv[2])
