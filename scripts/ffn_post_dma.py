"""Frozen matched-loader parents and the finite two-stage post-DMA experiment."""
from pathlib import Path
import json
from ffn_adaptive import ROOT, copy_tree, dump, rank as original_rank, features
from ffn_post_dma_power_review import reviewed
from ffn_residual import prove_bias32, prove_zero_schedule

REPORT = ROOT/'reports/optimization/ffn_post_dma'
BUILD = ROOT/'build/optimization/ffn_post_dma'
MANIFESTS = ROOT/'constraints/ffn_post_dma/candidates'


def rank(row):
    return original_rank(reviewed(row))


def load(name):
    return json.loads((MANIFESTS/(name+'.json')).read_text())


def candidates():
    return {p.stem: json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}


def prior_manifest(name):
    if name.startswith('ffn_pd_'):return load(name)
    from ffn_loading_dma import load as previous
    return previous(name)


def snapshot(row, folder):
    path=folder/'parent.json'
    if path.exists():return json.loads(path.read_text())
    manifest=prior_manifest(row['variant'])
    config=json.loads((ROOT/'build/optimization/complete_soc'/row['variant']/'configuration.json').read_text())
    copy_tree(ROOT/config['source_snapshot'],folder/'rtl_sources')
    copy_tree(ROOT/config['firmware'],folder/'firmware')
    program=ROOT/config['firmware']/'input-files'
    if not program.exists():program=ROOT/manifest['parent']['program']
    copy_tree(program,folder/'program')
    metadata=json.loads((folder/'firmware/firmware.json').read_text())
    record=dict(variant=row['variant'],state=row,configuration=config,features=features(row),
        effective_changes=manifest['effective_changes'],profile=json.loads((ROOT/row['profile']).read_text()),
        compiler=metadata.get('compiler',manifest['compiler']),pio_program=manifest['pio_program'],
        firmware=(folder/'firmware').relative_to(ROOT).as_posix(),
        source_snapshot=(folder/'rtl_sources').relative_to(ROOT).as_posix(),
        program=(folder/'program').relative_to(ROOT).as_posix(),
        layout=manifest['layout'],dma=manifest['dma'],output_dma=manifest['output_dma'],
        flook=manifest.get('flook',False))
    dump(path,record)
    return record


def freeze():
    path=BUILD/'frozen/parents.json'
    if path.exists():return json.loads(path.read_text())
    selected=None
    for namespace in ['ffn_transport','ffn_codegen_schedule','ffn_loading_dma']:
        prior=ROOT/'reports/optimization'/namespace
        files=[prior/n for n in ['delivery-status.json','final-selection.json','local-sync-confirmed.json']]
        if not all(p.exists() for p in files):return None
        status,selection,ack=[json.loads(p.read_text()) for p in files]
        if not status.get('complete') or not selection.get('complete'):return None
        winner=selection['winner']
        if ack.get('winner')!=winner['variant'] or not ack.get('verified_local_archive'):return None
        mapped=ROOT/'reports/optimization/complete_soc'/winner['variant']/'mapped_evaluation.json'
        if not mapped.exists() or not all(r['passed'] for r in json.loads(mapped.read_text())):return None
        if not winner.get('assessment_clock_gating',{}).get('passed'):return None
        if namespace=='ffn_loading_dma':selected=selection
    if not selected.get('native_power_precision_refreshed'):return None
    rows={r['variant']:r for r in selected['ranking']}
    dma_rows=[rows[n] for n in ['ffn_ld_D1','ffn_ld_D2','ffn_ld_T_D1','ffn_ld_T_D2']]
    best=min(dma_rows,key=original_rank)
    tile=prior_manifest(best['variant'])['layout']=='tile'
    direct='ffn_ld_T_D' if tile else 'ffn_ld_D'
    other='ffn_ld_D' if tile else 'ffn_ld_T_D'
    chosen=dict(W=selected['winner'],D0=rows[direct+'1'],D1=rows[direct+'2'],
                OTHER0=rows[other+'1'],OTHER1=rows[other+'2'])
    parents={key:snapshot(row,BUILD/'frozen'/row['variant']) for key,row in chosen.items()}
    dump(BUILD/'frozen/previous-selection.json',selected)
    dump(path,parents)
    return parents


def create(label,parent,hardware=(),flook=None,layout=None,output_dma=None,purpose='experiment'):
    name='ffn_pd_'+label
    layout=parent['layout'] if layout is None else layout
    output_dma=parent['output_dma'] if output_dma is None else bool(output_dma)
    flook=parent.get('flook',False) if flook is None else bool(flook)
    delta=list(hardware)
    if layout!=parent['layout']:delta.append('LAYOUT')
    inherited=parent['effective_changes'].get('post_dma_hardware',[])
    effective=dict(parent['effective_changes'],loading_layout=layout,output_dma=output_dma,
                   post_dma_hardware=sorted(set(inherited)|set(hardware)),post_dma_flook=flook)
    record=dict(variant=name,parent_variant=parent['variant'],parent=parent,
        features=parent['features'],effective_changes=effective,
        changes=dict(stream=True,small_input=True,row_group=1,double_buffer=True),
        layout=layout,dma=parent['dma'],output_dma=output_dma,flook=flook,
        hardware=delta,purpose=purpose,pio_program=parent['pio_program'],compiler=parent['compiler'],
        loader='required_data_v1',objective=['mean_task_energy','throughput','budget_area'],
        numerical_package='models/kwt_unified_optimized_v1')
    path=MANIFESTS/(name+'.json')
    if path.exists() and json.loads(path.read_text())!=record:raise RuntimeError('Frozen post-DMA candidate differs: '+name)
    if not path.exists():dump(path,record)
    return name


def adopt(row):
    return snapshot(row,BUILD/'accepted_parents'/row['variant'])


def same_rtl(name,manifest):
    source=ROOT/manifest['parent']['source_snapshot'];target=ROOT/'build/optimization/rtl_sources'/name
    files=lambda p:{f.relative_to(p).as_posix():f.read_bytes() for f in p.rglob('*') if f.suffix in ['.sv','.v','.svh']}
    if files(source)!=files(target):raise RuntimeError('Reused accelerator RTL differs: '+name)
    previous=ROOT/'build/optimization/complete_soc'/manifest['parent']['variant'];current=ROOT/'build/optimization/complete_soc'/name
    for leaf in ['kwt_complete_soc.sv','e203_subsys_main.v','e203_subsys_top.v','e203_subsys_perips.v',
                 'kwt_shared_dma_icb_sm40.sv','kwt_loading_dma_accelerator.sv','kwt_loading_dma_endpoint.svh']:
        a,b=previous/leaf,current/leaf
        if a.exists()!=b.exists() or (a.exists() and a.read_bytes()!=b.read_bytes()):
            raise RuntimeError('Reused generated SoC differs: '+name+' '+leaf)
