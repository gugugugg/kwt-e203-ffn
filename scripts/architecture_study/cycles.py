"""Local cold-window transport predictions using the already calibrated IR components."""
import gzip
import json
from common import ROOT,REPORT,dump,Core,arrays
from cores import CoreA,CoreC
from model import trace_rows
from native_model import NativeWrapper,NATIVE,cpu_request
from native_simulate import idle_cpu,empty_external,safe


def operations(rows):
    result=[('pio',8,5),('pio',12,0),('dma',0xa003a000,64,0),
            ('pio',8,0),('pio',12,0),('pio',0x18,1)]
    result.append(('dma',0xa0000000,rows*32,0))
    for row in range(0,99,rows):
        if row+rows<99:
            following=min(rows,99-row-rows)
            result.append(('dma',0xa0000000+(row+rows)*128,following*32,0))
        result.append(('dma',0xa0010000+row*512,min(rows,99-row)*128,1))
    return result


def run(route,layer):
    path=REPORT/('cycles/%s-layer-%02d.json'%(route,layer))
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    wrapper=NativeWrapper(numeric=False)
    wrapper.core=CoreA(layer=layer,numeric=True) if route=='A' else CoreC(layer=layer,numeric=False)
    # Preserve the observed case1 prefix. It contains no MAC yet; all twelve cases
    # use the same dimensions and transfer lengths. Layer-specific term work starts only after loading.
    for row in trace_rows(NATIVE/'native-events.csv'):
        wrapper.memory.context(row)
        cpu=cpu_request(row);c=wrapper.comb(cpu)
        wrapper.tick(cpu,c,row['cycle'])
        if c['launch']:
            assert row['cycle']==12112
            break
    row_group=4 if route=='A' else 2
    ops=operations(row_group);current=None;response_pending=False
    # Replace only already committed data values, at the identical observed prefix
    # boundary, for numeric A. No data is made ready earlier.
    x,w,b,sh,expected=arrays(layer)
    if route=='A':
        for i in range(3168):wrapper.memory.storage[i]=int(x.reshape(-1)[2*i]&65535)|int((x.reshape(-1)[2*i+1]&65535)<<16)
    expected_words=[int(v[0]&65535)|int((v[1]&65535)<<16) for v in expected.reshape(-1,2)]
    launches=[dict(cycle=12112,kind=1,address=0xa0020000,words=8704,direction=0)]
    counts=dict(compute_clocks=0,quantization_blocked=0,input_wait=0,input_reads=0,input_writes=0,
                weight_reads=0,products=0,seeds=0,output_bank_accesses=0,max_output_ports=0)
    input_slots={}
    first_mac=last_mac=last_commit=ack=None
    stream=None
    if layer==0:stream=gzip.open(REPORT/('%s-case1-events.jsonl.gz'%route),'wt',encoding='utf-8')
    try:
        for cycle in range(12113,2000000):
            wrapper.memory.context(empty_external());cpu=idle_cpu()
            if current is None and safe(wrapper) and not response_pending and ops:current=ops.pop(0)
            if current and current[0]=='pio':cpu.update(valid=int(not response_pending),address=current[1],data=current[2])
            c=wrapper.comb(cpu)
            if current and current[0]=='dma' and safe(wrapper):
                c['launch']=dict(address=current[1],words=current[2],direction=current[3])
                launches.append(dict(cycle=cycle,kind=wrapper.load_kind,**c['launch']));current=None
            elif current and current[0]=='pio':
                if cpu['valid'] and c['cpu_ready']:response_pending=True
                if response_pending and c['cpu_valid']:response_pending=False;current=None
            core=wrapper.core;qc=core.comb(c['core_in']);q=core.queue
            read=core.input_read()
            read_k=core.inner+1 if core.state==7 else 0
            ports=[]
            if read:
                valid_rows=min(row_group,99-core.row)
                counts['input_reads']+=valid_rows
                counts['weight_reads']+=16//row_group
                if route=='A':
                    for r in range(core.row,core.row+valid_rows):
                        logical=r*64+read_k;bank=r%4;address=(r//4%2)*64+read_k
                        if input_slots.get((bank,address))!=logical:raise RuntimeError('A input identity read mismatch')
                        ports.append(bank)
                        if core.tile==63:input_slots.pop((bank,address))
            load=c['core_in']['load'] and wrapper.load_kind==0
            if load:
                logical=core.input_count;r,k=divmod(logical,64);counts['input_writes']+=1
                if route=='A':
                    bank=r%4;address=(r//4%2)*64+k
                    if (bank,address) in input_slots:raise RuntimeError('A input lifetime overwritten')
                    input_slots[(bank,address)]=logical;ports.append(bank)
            if len(ports)!=len(set(ports)):raise RuntimeError('A input single-port conflict')
            counts['compute_clocks']+=int(core.state==7)
            counts['quantization_blocked']+=int(core.state==8 and not qc['quant'])
            counts['input_wait']+=int(core.state in [6,15] and not core.complete())
            counts['products']+=qc['mac_mask'].bit_count();counts['seeds']+=qc['seed_mask'].bit_count()
            if qc['mac_mask']:
                if first_mac is None:first_mac=cycle
                last_mac=cycle
            if stream is not None and (read or load or qc['quant'] or qc['q']['pop_count'] or cycle%128==0):
                stream.write(json.dumps(dict(cycle=cycle,state=core.state,row=core.row,tile=core.tile,inner=core.inner,
                    phase=getattr(core,'phase',0),input_read=read,input_write=load,
                    quant=qc['quant'],item=core.item,retire=qc['q']['pop_count'],queues=q.snapshot()),separators=(',',':'))+'\n')
            active=wrapper.engine.pd_active;writes=wrapper.memory.writes
            wrapper.tick(cpu,c,cycle)
            if route=='A':
                out_ports=getattr(q,'last_ports',[])
                counts['output_bank_accesses']+=len(out_ports)
                counts['max_output_ports']=max(counts['max_output_ports'],len(out_ports))
                if wrapper.memory.writes>writes:
                    address=wrapper.memory.commits[-1][1]
                    index=(address-0xa0010000)//4
                    if wrapper.memory.commits[-1][2]!=expected_words[index]:raise RuntimeError('A physical output value mismatch')
            if wrapper.memory.writes==12672 and last_commit is None:last_commit=wrapper.memory.commits[-1][0]
            if last_commit is not None and active and not wrapper.engine.pd_active:ack=cycle;break
        else:raise RuntimeError('Study model did not complete: %s/%d'%(route,layer))
    finally:
        if stream is not None:stream.close()
    assert wrapper.core.queue.retired==25344 and wrapper.memory.reads==11936 and counts['products']==1622016 and counts['seeds']==25344
    result=dict(route=route,layer=layer,passed=True,cold_cycles=last_commit+1,
                case_model_tasks_per_second=150000000/(last_commit+1),last_physical_commit=last_commit,final_ACK=ack,
                outputs=25344,ordered_identity=True,physical_values_checked=(route=='A'),DMA_reads=wrapper.memory.reads,
                DMA_writes=wrapper.memory.writes,descriptors=wrapper.engine.launches,counts=counts,
                first_logical_MAC=first_mac,last_logical_MAC=last_mac,queue_peak=wrapper.core.queue.peak,
                private_IO_macro_count=11 if route=='A' else 5,input_port_conflicts=0,output_port_conflicts=0,
                scope='Local prediction with preserved native case1 loading timeline and one-clock modeled descriptor issue; not new CPU or official hardware measurement',
                assumptions=['New datapath clock closure unmeasured','Same modeled descriptor interface as native-M1, not an instruction-accurate E203 driver',
                             '12-layer value-dependent C estimates reuse the same causally observed loading/control prefix; other eleven native CPU timelines were not captured'])
    dump('cycles/%s-layer-%02d.json'%(route,layer),result)
    dump('launches/%s-layer-%02d.json'%(route,layer),launches)
    print('ARCHITECTURE_CYCLE_PASS',route,layer,last_commit+1,flush=True)
    return result


def main():
    results=[run('A',0)]
    for layer in range(12):results.append(run('C',layer))
    dump('cycle-results.json',dict(results=results,route_A_timing_data_independent=True,
         route_A_12case_cycles_inferred_from_fixed_schedule=results[0]['cold_cycles'],
         route_C_12case_model_throughput=12*150000000/sum(r['cold_cycles'] for r in results if r['route']=='C'),
         measured_new_hardware=False))


if __name__=='__main__':main()
