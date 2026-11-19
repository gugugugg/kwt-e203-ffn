"""Build explicit reviewed net rules and expectations without changing the original map."""
from pathlib import Path
from collections import defaultdict
import argparse,json,re,struct
from ffn_c_final_energy import ROOT,REPORT,dump,review_group

def f32(x):return struct.unpack('f',struct.pack('f',x))[0]

def assemble(name):
    out=REPORT/'activity-mapping'/('native-review-'+review_group(name))/name
    inv=json.loads((out/'inventory.json').read_text());conn=json.loads((out/'connectivity.json').read_text())
    raw=json.loads((out/'saif-index.json').read_text());act=raw['activity'];review=json.loads((out/'corrections-draft.json').read_text())
    if review['pending']:raise RuntimeError('Read outstanding actual phase review: '+name)
    suppressed=set(review.get('suppressed_opposite_phase_aliases',[]));aliases=[r for r in review['aliases'] if r['rtl'] not in suppressed];overrides={r['rtl']:r for r in aliases};replaced=review['replace_native_cell_aliases']
    original=ROOT/'build/server'/('complete_soc_sm40_'+inv['tag'])/'saif_map.tcl';keep=[];removed=[];removed_net_rules=[]
    for i,line in enumerate(original.read_bytes().splitlines(keepends=True),1):
        m=re.match(rb'set_rtl_to_gate_name -rtl \{([^}]+)\} -gate \[get_cell \{[^}]+\}\] -inverted\s*$',line)
        net_rule=re.match(rb'set_rtl_to_gate_name -rtl \{([^}]+)\} -gate \{[^}]+\}(?: -inverted)?\s*$',line)
        if m and m.group(1).decode() in replaced:removed.append(dict(rtl=m.group(1).decode(),line=i,command=line.decode().rstrip('\r\n')))
        elif net_rule and net_rule.group(1).decode() in set(overrides)|suppressed:removed_net_rules.append(dict(rtl=net_rule.group(1).decode(),line=i,command=line.decode().rstrip('\r\n')))
        else:keep.append(line)
    assert sorted(r['rtl'] for r in removed)==sorted(replaced)
    drafts=out/'reviewed-draft';drafts.mkdir(exist_ok=True)
    filtered=drafts/(name+'-native-map-filtered.tcl');filtered.write_bytes(b''.join(keep))
    dump(drafts/'native-map-replay.json',dict(original=original.relative_to(ROOT).as_posix(),original_unchanged=True,retained_lines_byte_identical=True,removed_cell_rules=removed,removed_overridden_net_rules=removed_net_rules,filtered_map=filtered.relative_to(ROOT).as_posix()))
    by_rtl={r['rtl']:r for r in inv['mappings']};cellphases={r['rtl']:r for r in json.loads((out/'physical-cell-phase-review.json').read_text())}
    reps=conn['representatives'];groups=defaultdict(list)
    def rep(n):return reps.get(n,n)
    for rtl,stats in act.items():
        if rtl in suppressed:continue
        row=overrides.get(rtl,by_rtl.get(rtl))
        if row is None:
            if rtl in reps:groups[rep(rtl)].append(dict(rtl=rtl,gate=rtl,inverted=False,raw=stats))
            continue
        gate=row['gate'];negative=row['inverted']
        if row.get('cell'):
            c=inv['cells'].get(gate)
            if c is None:continue
            pin='Q' if 'Q' in c['pins'] else 'QN' if 'QN' in c['pins'] else None
            if pin is None:continue
            gate=conn['pins'][gate+'/'+pin]
            negative=cellphases[rtl]['physical_inverted'] if rtl in cellphases else False
        groups[rep(gate)].append(dict(rtl=rtl,gate=gate,inverted=bool(negative),raw=stats))
    collisions=[]
    def corrected_stats(s):
        v=dict(s['raw'])
        if s['inverted']:v['T0'],v['T1']=v['T1'],v['T0']
        return tuple(sorted(v.items()))
    for key,rows in groups.items():
        if len({corrected_stats(r) for r in rows})>1:collisions.append(dict(segment=key,sources=rows,drivers=conn['drivers'].get(key,[])))
    dump(out/'corrected-injection-collisions.json',collisions)
    # Every new accumulator/carry/return/shift boundary plus the actual macro and ICG pins.
    nets=[r['gate'] for r in aliases]+[by_rtl[rtl]['gate'] for rtl in suppressed if rtl in by_rtl and not by_rtl[rtl]['cell']]
    pin_evidence=[]
    for row in inv['registers']:
        pin='Q' if 'Q' in row['pins'] else 'QN'
        nets.append(conn['pins'][row['cell']+'/'+pin])
    for gate in inv['gates']:
        for pin in ['CK','E','TE','Q']:
            n=conn['pins'].get(gate['cell']+'/'+pin)
            if n:nets.append(n)
    # Macro bit nets are taken from native segment results, preserving physical bit identities.
    from c_final_energy_phase_review import native_index
    native=native_index(out/'segments.rpt')
    native.update(native_index(out/'additional-segments/segments.rpt'))
    all_macros=inv['input_macros']+json.loads((out/'weight-macros.json').read_text())
    for macro in all_macros:
        for stem,count in [('D',16),('Q',16),('WEN',16),('A',10 if macro['ref']=='RAMSP1024X16' else 7)]:
            for bit in range(count):
                key=('pin',macro['cell']+'/'+stem+'[%d]'%bit);entry=native.get(key)
                if entry and entry['nets']:nets.append(entry['nets'][0]);pin_evidence.append(dict(pin=key[1],net=entry['nets'][0]))
        for pin in ['CLK','CEN','GWEN']:
            key=('pin',macro['cell']+'/'+pin);entry=native.get(key)
            if entry and entry['nets']:nets.append(entry['nets'][0]);pin_evidence.append(dict(pin=key[1],net=entry['nets'][0]))
    # Retained encoded-positive cells remain part of the direct verification.
    for row in cellphases.values():nets.append(row['net'])
    extra=out/'phase-extra-segments/segments.rpt'
    if extra.exists():
        for row in native_index(extra).values():
            if row['nets']:nets.append(row['nets'][0])
    # Keep representative FIFO unknowns visible before update_power.
    for bit in [224,240]:
        rtl='soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/output_queue/fifo['+str(bit)+']'
        if rtl in by_rtl and not by_rtl[rtl]['cell']:nets.append(by_rtl[rtl]['gate'])
    nets=list(dict.fromkeys(nets))
    # Resolve only literal buffer/inverter propagation when the queried net has no file source.
    vendor=(out/'vendor-functions.v').read_text();models={m.group(1):m.group(2).split('specify')[0] for m in re.finditer(r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule',vendor)}
    def expected(net,seen=None):
        key=rep(net)
        if key in groups:return dict(net=net,sources=groups[key],source='file',chain=[])
        seen=set() if seen is None else seen
        if key in seen:return None
        seen.add(key);drivers=conn['drivers'].get(key,[])
        if len(drivers)!=1:return None
        dr=drivers[0];cell=inv['cells'][dr['cell']];body=models.get(cell['ref'],'');pin=dr['pin']
        if 'I' not in cell['pins'] or pin not in ['Z','ZN']:return None
        if not re.search(r'\b'+('not' if pin=='ZN' else 'buf')+r'\s+\w+\s*\(\s*'+pin+r'\s*,\s*I\s*\)',body):return None
        n=conn['pins'][dr['cell']+'/I'];up=expected(n,seen)
        if up is None:return None
        return dict(net=net,sources=[dict(s,propagation_inversions=s.get('propagation_inversions',[])+[pin=='ZN']) for s in up['sources']],source='forward_implied',chain=[dr]+up['chain'])
    expectations={};missing=[]
    for n in nets:
        x=expected(n)
        if x is None:missing.append(dict(net=n,drivers=conn['drivers'].get(rep(n),[])));continue
        for s in x['sources']:
            stats=s['raw'];known=stats['T0']+stats['T1']
            if not known:s['expected']=None;continue
            sp=f32(stats['T1']/known)
            if s['inverted']:sp=f32(1-sp)
            for flip in s.get('propagation_inversions',[]):
                if flip:sp=f32(1-sp)
            s['expected']=dict(SP=format(sp,'.6g'),TR=format(f32(f32(stats['TC'])/f32(float(raw['duration']))),'.6g'))
        expectations[n]=x
    dump(out/'phase-expectations.json',dict(duration=raw['duration'],duration_binary32=f32(float(raw['duration'])),nets=expectations,unresolved=missing))
    dump(out/'macro-physical-probe-pins.json',pin_evidence)
    lines=['reset_rtl_to_gate_name']
    lines+=['set_rtl_to_gate_name -rtl {%s} -gate {%s}%s'%(r['rtl'],r.get('gate_pin',r['gate']),' -inverted' if r['inverted'] else '') for r in aliases]
    lines+=['source {%s}'%filtered.relative_to(ROOT).as_posix()]
    lines+=['unset_rtl_to_gate_name {%s}'%rtl for rtl in sorted(suppressed)]
    marker='XPIAN_COLUMN_PARALLEL_ACTIVITY_VERIFIED %s inverted=%d suppressed=%d replaced_cell_rules=%d'%(name,sum(r['inverted'] for r in aliases),len(suppressed),len(replaced))
    lines+=['puts "'+marker+'"','proc ffn_report_reviewed_activity {directory} {','set f [open $directory/activity-phase-review.rpt w]','foreach object {%s} {'%' '.join('{%s}'%n for n in nets),'set net [get_nets $object]','puts $f "NET [get_object_name $net]"','puts $f "SP [get_switching_activity -static_probability $net]"','puts $f "TR [get_switching_activity -toggle_rate $net]"','}','close $f','}']
    (drafts/(name+'.tcl')).write_text('\n'.join(lines)+'\n')
    dump(drafts/(name+'.json'),dict(review,tag=inv['tag'],status='actual_netlist_reviewed_native_probe_pending',probe_nets=nets,review_revision='literature_power_actual_final_v1',native_probe_passed=False,inversion_count=sum(r['inverted'] for r in aliases)))
    print(name,'probe_nets',len(nets),'expected',len(expectations),'unresolved',len(missing),'corrected_injection_collisions',len(collisions),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('variants',nargs='+')
    for name in p.parse_args().variants:assemble(name)
