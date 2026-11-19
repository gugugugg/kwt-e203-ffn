"""Frozen accepted parents and exact residual FFN experiments."""
from pathlib import Path
import json
import struct
import re
from ffn_adaptive import ROOT,copy_tree,dump,rank,features
REPORT=ROOT/'reports/optimization/ffn_residual'
BUILD=ROOT/'build/optimization/ffn_residual'
MANIFESTS=ROOT/'constraints/ffn_residual/candidates'


def candidates():return {p.stem:json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}
def load(name):return json.loads((MANIFESTS/(name+'.json')).read_text())


def parent_record(row,folder):
    name=row['variant'];cfg=json.loads((ROOT/'build/optimization/complete_soc'/name/'configuration.json').read_text())
    changes={}
    for group in ['ffn_round3','ffn_adaptive','ffn_adaptive_next','ffn_residual']:
        p=ROOT/'constraints'/group/'candidates'/(name+'.json')
        if p.exists():
            m=json.loads(p.read_text());changes=m.get('effective_changes',m.get('changes',{}))
    source=ROOT/cfg['source_snapshot'];text=(source/'encoder/kwt_encoder.sv').read_text()
    group_match=re.search(r'ROW_GROUP=(\d+)',text);cache_match=re.search(r'USE_ROW_CACHE=(\d+)',text)
    changes=dict(changes,row_pair=(int(group_match.group(1))>1 if group_match else 'row_stash' in text),row_cache=(bool(int(cache_match.group(1))) if cache_match else 'row_cache[' in text))
    if group_match:changes['row_group']=int(group_match.group(1))
    copy_tree(source,folder/'rtl_sources');copy_tree(ROOT/cfg['firmware'],folder/'firmware')
    p=dict(variant=name,state=row,features=features(row),effective_changes=changes,configuration=cfg,
           profile=json.loads((ROOT/row['profile']).read_text()),
           source_snapshot=str((folder/'rtl_sources').relative_to(ROOT)),firmware=str((folder/'firmware').relative_to(ROOT)))
    dump(folder/'parent.json',p);return p


def freeze():
    folder=BUILD/'frozen_previous'
    if (folder/'parents.json').exists():return json.loads((folder/'parents.json').read_text())
    previous=ROOT/'reports/optimization/ffn_adaptive_next'
    status=previous/'delivery-status.json';selection=previous/'final-selection.json';ack=previous/'local-sync-confirmed.json'
    if not all(p.exists() for p in [status,selection,ack]):return None
    s=json.loads(selection.read_text());a=json.loads(ack.read_text())
    if not json.loads(status.read_text()).get('complete') or not s.get('complete') or not s.get('native_power_precision_refreshed'):return None
    if a.get('winner')!=s['winner']['variant']:return None
    chosen={'winner':s['winner']}
    for family,wide in [('eight',False),('sixteen',True)]:
        rows=[r for r in s['ranking'] if features(r)['lanes16']==wide]
        chosen[family]=min(rows,key=rank)
        paired=[r for r in rows if r['variant'] in ['ffn_next_'+family+'_R','ffn_next_'+family+'_SR']]
        if paired:chosen[family+'_r2']=min(paired,key=rank)
    parents={key:parent_record(row,folder/row['variant']) for key,row in chosen.items()}
    dump(folder/'previous-selection.json',s);dump(folder/'parents.json',parents)
    return parents


def create(parent,family,label,changes,purpose='experiment'):
    name='ffn_res_'+family+'_'+label
    m=dict(variant=name,parent_variant=parent['variant'],parent=parent,features=parent['features'],changes=changes,
           effective_changes=dict(parent.get('effective_changes',{}),**changes),purpose=purpose,
           numerical_package='models/kwt_unified_optimized_v1',objective=['mean_task_energy','throughput','budget_area'])
    path=MANIFESTS/(name+'.json')
    if path.exists() and json.loads(path.read_text())!=m:raise RuntimeError('Different frozen experiment: '+name)
    if not path.exists():dump(path,m)
    return name


def prove_bias32(destination):
    rows=[];values=[]
    for layer in range(12):
        source=ROOT/'build/optimization/ffn_residual/testdata'/('layer_%02d_parameters.bin'%layer)
        words=source.read_bytes()
        image=ROOT/'build/optimization/images/Q2_range'/('linear_layer_%02d_parameters.hex'%layer)
        if image.exists():
            supplied=b''.join(struct.pack('<I',int(v,16)) for v in image.read_text().split())
            if supplied!=words:raise RuntimeError('Actual CPU parameter image differs from the frozen numerical package')
        bias=list(struct.unpack('<256q',words[16384*2:]))
        if any(v!=struct.unpack('<i',struct.pack('<I',v&0xffffffff))[0] for v in bias):
            raise RuntimeError('Frozen Q2 bias is not a signed32 sign extension')
        rows.append(dict(layer=layer,minimum=min(bias),maximum=max(bias),source=str(source.relative_to(ROOT)),count=len(bias)))
        values+=bias
    result=dict(passed=True,minimum=min(values),maximum=max(values),layers=rows,count=len(values),
                external_bits=64,stored_bits=32,accumulator_bits=36,domain='frozen Q2 package only')
    dump(destination,result);return result

def prove_zero_schedule(manifest,source,destination):
    """Address-domain induction, independent of input values and output stalls."""
    text=(source/'encoder/kwt_encoder.sv').read_text();compact=''.join(text.split())
    for condition in ['parameter_count==17408','shift_count==128','fifo_count!=0']:
        if condition not in compact:raise RuntimeError('Coverage invariant missing from candidate: '+condition)
    e=manifest['effective_changes'];group=e.get('row_group',2 if e.get('row_pair') else 1)
    if e.get('stream'):
        if 'input_complete' not in compact or 'input_count)>=(row+' not in compact:
            raise RuntimeError('Stream input group is not guarded by this task load count')
    elif 'input_count!=6336' not in compact:raise RuntimeError('Full input write coverage is not required before start')
    reads=set();blocks=[]
    for row in range(0,99,group):
        end=min(99,row+group);local={r*64+i for r in range(row,end) for i in range(64)}
        if not local.issubset(set(range(end*64))):raise RuntimeError('Input read outside completed current-task writes')
        reads|=local;blocks.append(dict(first_row=row,rows=end-row,last_required_input_count=end*64))
    weights={inner*256+column for inner in range(64) for column in range(256)}
    shifts={column//2 for column in range(256)}
    if reads!=set(range(6336)) or weights!=set(range(16384)) or shifts!=set(range(128)):
        raise RuntimeError('Residual storage address coverage incomplete')
    stash_cols={tile*(16 if manifest['features']['lanes16'] else 8)+lane for tile in range(256//(16 if manifest['features']['lanes16'] else 8)) for lane in range(16 if manifest['features']['lanes16'] else 8)}
    if stash_cols!=set(range(256)):raise RuntimeError('Stash is read before every column can be written')
    result=dict(passed=True,method='current-task monotone-load guards plus exact address-domain induction',
        independent_of='all int16 inputs and legal consumer pauses',input_read_addresses=len(reads),weight_read_addresses=len(weights),
        shift_read_addresses=len(shifts),bias_values=256,blocks=blocks,stash_columns_per_row=len(stash_cols),
        rules=['Parameter and shift counters reach complete packet lengths before START_LAYER',
               'Each row group starts only after its current-task input prefix is written',
               'Every accumulator is overwritten with its column bias before inner=0',
               'Stash reads follow all 256 column writes for the corresponding row group',
               'FIFO/cache validity and task load counters reset; previous-task content is never accepted'],
        source_snapshot=str(source.relative_to(ROOT)))
    dump(destination,result);return result
