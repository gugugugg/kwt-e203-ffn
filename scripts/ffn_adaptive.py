"""Result-driven FFN experiments; round-three artifacts remain immutable inputs."""
from pathlib import Path
import json
import shutil
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/optimization/ffn_adaptive'
MANIFESTS=ROOT/'constraints/ffn_adaptive/candidates'
BUILD=ROOT/'build/optimization/ffn_adaptive'


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2),encoding='utf-8')
    temporary.replace(path)


def copy_tree(source,destination):
    destination.mkdir(parents=True,exist_ok=True)
    for p in source.rglob('*'):
        target=destination/p.relative_to(source)
        if p.is_dir():target.mkdir(parents=True,exist_ok=True)
        else:
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)


def rank(row):
    return (row['mean_energy_j'],-row['throughput_per_second'],
            row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'])


def features(row):
    return dict(row.get('features',dict(split_bias=False,unroll=False,fast_pair=False,
                                      overlap=False,clock_gating=False,lanes16=False)))


def candidates():
    return {p.stem:json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}


def load(variant):
    return json.loads((MANIFESTS/(variant+'.json')).read_text())


def freeze_round3():
    target=BUILD/'frozen_round3'
    if (target/'parents.json').exists():return json.loads((target/'parents.json').read_text())
    delivery=ROOT/'reports/optimization/ffn_round3/delivery-status.json'
    if not delivery.exists() or not json.loads(delivery.read_text()).get('complete'):return None
    selection=json.loads((ROOT/'reports/optimization/ffn_round3/final-selection.json').read_text())
    if not selection.get('complete') or not selection.get('native_power_precision_refreshed'):return None
    rows=selection['ranking']
    dump(target/'round3-selection.json',selection)
    chosen={'winner':selection['winner'],
            'eight':min((r for r in rows if not features(r)['lanes16']),key=rank),
            'sixteen':min((r for r in rows if features(r)['lanes16']),key=rank)}
    parents={}
    for family,row in chosen.items():
        variant=row['variant'];folder=target/variant
        if not (folder/'parent.json').exists():
            config=json.loads((ROOT/'build/optimization/complete_soc'/variant/'configuration.json').read_text())
            copy_tree(ROOT/config['source_snapshot'],folder/'rtl_sources')
            copy_tree(ROOT/config['firmware'],folder/'firmware')
            profile=json.loads((ROOT/row['profile']).read_text())
            record={'variant':variant,'state':row,'features':features(row),'configuration':config,'profile':profile,
                    'source_snapshot':str((folder/'rtl_sources').relative_to(ROOT)),
                    'firmware':str((folder/'firmware').relative_to(ROOT))}
            dump(folder/'parent.json',record)
        parents[family]=json.loads((folder/'parent.json').read_text())
    dump(target/'parents.json',parents)
    return parents


def create(parent,label,changes,purpose='experiment'):
    name='ffn_adp_'+parent['variant'].replace('ffn_v3_','').replace('ffn_v2_','').replace('ffn_adp_','')+'_'+label
    manifest={'variant':name,'parent_variant':parent['variant'],'parent':parent,
              'features':dict(parent['features']),'changes':changes,'purpose':purpose,
              'effective_changes':dict(parent.get('effective_changes',{}),**changes),
              'numerical_package':'models/kwt_unified_optimized_v1',
              'objective':['mean_task_energy','throughput','budget_area']}
    path=MANIFESTS/(name+'.json')
    if path.exists():
        if json.loads(path.read_text())!=manifest:raise RuntimeError('Candidate name already has a different experiment: '+name)
    else:dump(path,manifest)
    return name


def clear_depth(f):
    lanes=16 if f['lanes16'] else 8
    return max(1024,16384//lanes if f['split_bias'] else 3072,128)


def select_measured(parent,rows):
    qualified=[r for r in rows if r.get('stage')=='formal_passed' and r.get('power_passed')]
    return min([parent['state']]+qualified,key=rank)
