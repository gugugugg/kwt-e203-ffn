"""Matched minimal-loader, Tile-layout and DMA comparisons after both delivered rounds."""
from pathlib import Path
import json
from ffn_adaptive import ROOT,copy_tree,dump,rank,features
from ffn_residual import prove_bias32,prove_zero_schedule

REPORT=ROOT/'reports/optimization/ffn_loading_dma'
BUILD=ROOT/'build/optimization/ffn_loading_dma'
MANIFESTS=ROOT/'constraints/ffn_loading_dma/candidates'


def load(name):return json.loads((MANIFESTS/(name+'.json')).read_text())


def candidates():return {p.stem:json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}


def snapshot(row,folder,effective):
    path=folder/'parent.json'
    if path.exists():return json.loads(path.read_text())
    config=json.loads((ROOT/'build/optimization/complete_soc'/row['variant']/'configuration.json').read_text())
    copy_tree(ROOT/config['source_snapshot'],folder/'rtl_sources')
    copy_tree(ROOT/config['firmware'],folder/'firmware')
    source=folder/'firmware/input-files'
    if source.exists():copy_tree(source,folder/'program')
    else:
        support=ROOT/'build/optimization/ffn_codegen_schedule/program_support'
        for name in ['software/cpu_integration/startup.S','software/unified_cpu/main.c','software/unified/kwt_unified_driver.h',
                     'software/cpu_integration/kwt_platform_addresses.h','software/cpu_integration/link.ld']:
            dest=folder/'program'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((support/name).read_bytes())
        for name in ['driver.c','kernels.S']:
            source=folder/'firmware'/name
            if source.exists():(folder/'program'/name).write_bytes(source.read_bytes())
    metadata=json.loads((folder/'firmware/firmware.json').read_text())
    record=dict(variant=row['variant'],state=row,configuration=config,features=features(row),effective_changes=effective,
        profile=json.loads((ROOT/row['profile']).read_text()),compiler=metadata.get('compiler',dict(optimization='O2',lto=False,gc_sections=False)),
        firmware=(folder/'firmware').relative_to(ROOT).as_posix(),source_snapshot=(folder/'rtl_sources').relative_to(ROOT).as_posix(),
        program=(folder/'program').relative_to(ROOT).as_posix())
    if row['variant'].startswith('ffn_ld_'):
        record['pio_program']=load(row['variant'])['pio_program']
    else:record['pio_program']=record['program']
    dump(path,record);return record


def freeze():
    path=BUILD/'frozen/parent.json'
    if path.exists():return json.loads(path.read_text())
    prior=ROOT/'reports/optimization/ffn_codegen_schedule'
    files=[prior/n for n in ['delivery-status.json','final-selection.json','local-sync-confirmed.json']]
    if not all(p.exists() for p in files):return None
    status,selection,ack=[json.loads(p.read_text()) for p in files]
    if not status.get('complete') or not selection.get('complete') or not selection.get('native_power_precision_refreshed'):return None
    row=selection['winner']
    if ack.get('winner')!=row['variant'] or not ack.get('verified_local_archive'):return None
    previous=ROOT/'reports/optimization/ffn_transport'
    if not all((previous/n).exists() for n in ['delivery-status.json','local-sync-confirmed.json']):return None
    mapped=ROOT/'reports/optimization/complete_soc'/row['variant']/'mapped_evaluation.json'
    if not mapped.exists() or not all(r['passed'] for r in json.loads(mapped.read_text())):return None
    if row['variant'].startswith('ffn_cg_'):
        from ffn_codegen_schedule import load as old_load
        effective=old_load(row['variant'])['effective_changes']
    elif row['variant'].startswith('ffn_tr_'):
        from ffn_transport import load as old_load
        effective=old_load(row['variant'])['effective_changes']
    else:
        effective=json.loads((ROOT/'build/optimization/ffn_transport/frozen_baseline/parent.json').read_text())['effective_changes']
    dump(BUILD/'frozen/previous-selection.json',selection)
    return snapshot(row,path.parent,effective)


def create(label,parent,layout='plain',dma=False,output_dma=False,purpose='experiment'):
    name='ffn_ld_'+label
    effective=dict(parent['effective_changes'],loading_layout=layout,loading_dma=bool(dma),output_dma=bool(output_dma))
    delta=[]
    if layout!=parent['effective_changes'].get('loading_layout','plain'):delta.append('TILE')
    if dma!=parent['effective_changes'].get('loading_dma',False):delta.append('DMA')
    record=dict(variant=name,parent_variant=parent['variant'],parent=parent,features=parent['features'],
        effective_changes=effective,changes=dict(stream=True,small_input=True,row_group=1,double_buffer=True),
        layout=layout,dma=bool(dma),output_dma=bool(output_dma),hardware=delta,purpose=purpose,
        pio_program=parent.get('pio_program',parent['program']),
        compiler=parent['compiler'],loader='required_data_v1',
        objective=['mean_task_energy','throughput','budget_area'],numerical_package='models/kwt_unified_optimized_v1')
    path=MANIFESTS/(name+'.json')
    if path.exists() and json.loads(path.read_text())!=record:raise RuntimeError('Frozen loading experiment differs: '+name)
    if not path.exists():dump(path,record)
    return name


def adopt(row):return snapshot(row,BUILD/'accepted_parents'/row['variant'],load(row['variant'])['effective_changes'])
