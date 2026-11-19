"""Frozen accepted IR, six literature-driven configurations and fixed objectives."""
import json
from ffn_joint_power import ROOT,copy_tree,dump,rank,joint_feasible,AREA_LIMIT,POWER_LIMIT,THROUGHPUT_MIN
from ffn_residual import prove_bias32,prove_zero_schedule

REPORT=ROOT/'reports/optimization/ffn_literature_power'
BUILD=ROOT/'build/optimization/ffn_literature_power'
MANIFESTS=ROOT/'constraints/ffn_literature_power/candidates'
FIRST=['WE','IE','BA','BW']
INDEPENDENT=FIRST+['M28']

def review_group(name):
    return 'first' if name in ['ffn_lit_'+label for label in FIRST] else name.replace('ffn_lit_','',1)

def load(name):
    return json.loads((MANIFESTS/(name+'.json')).read_text())

def candidates():
    return {p.stem:json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}

def freeze():
    path=BUILD/'frozen/parent.json'
    if path.exists():return json.loads(path.read_text())
    previous=ROOT/'reports/optimization/ffn_logic_power'
    acceptance=json.loads((previous/'local-acceptance-check.json').read_text())
    if not acceptance['passed'] or not acceptance['native_ack_confirmed']:
        raise RuntimeError('Read the completed round-eight local and native acceptance')
    selection=json.loads((previous/'final-selection.json').read_text())
    rows={r['variant']:r for r in selection['ranking']}
    row=rows['ffn_lp_IR']
    cfg=json.loads((ROOT/'build/optimization/complete_soc/ffn_lp_IR/configuration.json').read_text())
    manifest=json.loads((ROOT/'constraints/ffn_logic_power/candidates/ffn_lp_IR.json').read_text())
    folder=BUILD/'frozen/ffn_lp_IR'
    for origin,leaf in [(cfg['source_snapshot'],'rtl_sources'),(cfg['firmware'],'firmware')]:
        copy_tree(ROOT/origin,folder/leaf)
    program=ROOT/cfg['firmware']/'input-files'
    if not program.exists():program=ROOT/manifest['parent']['program']
    copy_tree(program,folder/'program')
    copy_tree(ROOT/cfg['linear_images'],BUILD/'frozen/images')
    metadata=json.loads((folder/'firmware/firmware.json').read_text())
    record=dict(variant=row['variant'],state=row,main_baseline=rows['ffn_tp_CROSS'],configuration=cfg,
        features=manifest['features'],effective_changes=manifest['effective_changes'],
        profile=json.loads((ROOT/row['profile']).read_text()),compiler=metadata.get('compiler',manifest['compiler']),
        pio_program=manifest['pio_program'],firmware=(folder/'firmware').relative_to(ROOT).as_posix(),
        source_snapshot=(folder/'rtl_sources').relative_to(ROOT).as_posix(),program=(folder/'program').relative_to(ROOT).as_posix(),
        layout=manifest['layout'],dma=True,output_dma=True,flook=manifest.get('flook',False))
    dump(BUILD/'frozen/previous-selection.json',selection)
    dump(path,record)
    (BUILD/'frozen/selected-original.json').write_bytes((ROOT/'constraints/ffn_selected.json').read_bytes())
    return record

def create(label,parent,changes=None):
    name='ffn_lit_'+label
    changes=list(changes if changes is not None else [label])
    effective=dict(parent['effective_changes'],literature_power_hardware=changes,row_group=2)
    row=dict(variant=name,parent_variant=parent['variant'],parent=parent,features=parent['features'],
        effective_changes=effective,changes=dict(stream=True,small_input=True,row_group=2,double_buffer=True),
        layout=parent['layout'],dma=True,output_dma=True,flook=parent['flook'],
        hardware=['S','H','M2','IR']+changes,literature_power_hardware=changes,purpose='experiment',
        pio_program=parent['pio_program'],compiler=parent['compiler'],loader='required_data_v1',
        objective=['joint_feasible','mean_task_energy','throughput','budget_area'],numerical_package='models/kwt_unified_optimized_v1')
    path=MANIFESTS/(name+'.json')
    if path.exists() and json.loads(path.read_text())!=row:
        raise RuntimeError('Read the frozen round-nine configuration: '+name)
    if not path.exists():dump(path,row)
    return name

def arithmetic_winner(parent,rows):
    family=[parent['state']]+[r for r in rows if r['variant'] in ['ffn_lit_BA','ffn_lit_BW','ffn_lit_M28']]
    legal=[r for r in family if r.get('stage')=='formal_passed' and r['throughput_per_second']>=THROUGHPUT_MIN
        and r['metrics']['area']['accelerator_budget_including_shared_interface_mm2']<AREA_LIMIT]
    return min(legal,key=rank)

def same_rtl(name,manifest):
    from ffn_tile_pipeline import same_rtl as previous
    return previous(name,manifest)
