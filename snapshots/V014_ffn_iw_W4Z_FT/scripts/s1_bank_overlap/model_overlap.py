"""Causal models for the accepted S1+B32 task and two shared SRAM schedules."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/q16_staged'))
import model_staged as staged
from model_staged import BASE, INPUT_WORDS, PARAMETER_WORD, PARAMETER_REQUEST, READY_WORD, SHIFT_WORD

m3, q16 = staged.m3, staged.q16
REPORT = ROOT/'reports/optimization/ffn_s1_bank_overlap'
TRACE = REPORT/('received/observation/native-evidence/reports/optimization/'
                'ffn_s1_bank_overlap/observation/events.csv')
ANCHORS = dict(first_mac=17640,last_emit=44959,final_physical_commit=45346,
               final_ack=45347,cold_cycles=45347)
START_STREAM = {'M0':8512,'N':4096,'I':1}
PARAMETER_END = PARAMETER_WORD+8448
SHIFT_END = SHIFT_WORD+64
PACINGS = ('response_relative','fixed_cpu')


def load_observation():
    commands, host, pending, rows = [], [], {}, {}
    for row in m3.trace_rows(TRACE):
        cycle = row['cycle']
        rows[cycle] = row
        for bus in ('cpu','shared_cpu'):
            if row[bus+'_cmd_valid'] and bus not in pending:
                pending[bus] = dict(bus=bus,start=cycle,**{
                    key:row[bus+'_cmd_'+signal] for key,signal in
                    (('read','read'),('address','addr'),('data','wdata'),('mask','wmask'))})
            if row[bus+'_cmd_valid'] and row[bus+'_cmd_ready']:
                pending[bus]['accept'] = cycle
            if row[bus+'_rsp_valid'] and row[bus+'_rsp_ready'] and bus in pending:
                commands.append(dict(pending.pop(bus),response=cycle))
        if row['host_cmd_valid'] and row['host_cmd_ready']:
            assert not row['host_cmd_read'] and row['host_cmd_wmask']==15
            host.append((cycle,row['host_cmd_addr'],row['host_cmd_wdata']))
    commands.sort(key=lambda command:command['start'])
    prior = 0
    for command in commands:
        command['gap'] = command['start']-prior
        assert command['gap']>0
        prior = command['response']
    initial = [(addr,data) for _,addr,data in host[128:137]]
    parameter_cycle, parameter_address, _ = host[137]
    request_cycle = next(c['accept'] for c in commands if c['address']==PARAMETER_REQUEST)
    assert len(host)==11690 and parameter_address==PARAMETER_WORD
    assert [a for _,a,_ in host[:128]]==list(range(128))
    assert host[137+8512][1:]==(READY_WORD,1)
    assert [a for _,a,_ in host[137+8513:]]==list(range(128,INPUT_WORDS))
    return commands,initial,host[0][0],parameter_cycle-request_cycle,rows


def physical_word(mode, logical):
    if mode=='I' and PARAMETER_WORD<=logical<PARAMETER_WORD+8192:
        offset = logical-PARAMETER_WORD
        return PARAMETER_WORD+((offset&1)<<12)+(offset&0xffe)+((offset>>12)&1)
    return logical


def word_address(cmd):
    return (cmd['address']-BASE)//4


def parameter_word(word):
    return PARAMETER_WORD<=word<PARAMETER_END


def shift_word(word):
    return SHIFT_WORD<=word<SHIFT_END


def qualified_dma_read(cmd):
    word = word_address(cmd)
    return bool(cmd['read'] and not cmd['address']%4 and (parameter_word(word) or shift_word(word)))


class BankPort(staged.SharedPort):
    def __init__(self,wrapper,mode):
        super().__init__(wrapper,True)
        self.mode = mode
        self.parameter_prefix = self.shift_prefix = 0
        self.dual = self.conflicts = self.param_wait = 0
        self.stream_start = self.last_parameter_host = self.last_shift_host = None

    def committed(self,word):
        if parameter_word(word):
            index = word-PARAMETER_WORD
            if self.mode=='N':
                return self.parameter_prefix>=min(((index//4096)+1)*4096,8448)
            return index<self.parameter_prefix
        return self.shift_prefix==64

    def comb(self):
        if self.mode=='M0':
            return super().comb()
        ext, w = self.external, self.wrapper
        engine = w.engine
        raw_b = engine.commands(w.core.capacity(w.load_kind),len(w.core.queue.held)>=2)['memory']
        a, host = ext['shared'], ext['host']
        hword = host['address']
        hfull = host['valid'] and not host['read'] and host['mask']==15
        stream = bool(hfull and self.background_phase and
                      ((parameter_word(hword) and hword==PARAMETER_WORD+self.parameter_prefix) or
                       (shift_word(hword) and hword==SHIFT_WORD+self.shift_prefix)))
        background = bool(hfull and self.background_phase and self.parameter_prefix==8448 and
                          self.shift_prefix==64 and hword==self.prefix and self.prefix<INPUT_WORDS)
        foreground = host['valid'] and not (stream or background)
        input_wait = (m3.input_read(raw_b) and self.prefix<INPUT_WORDS and
                      self.prefix//128<=word_address(raw_b)//128)
        parameter_wait = qualified_dma_read(raw_b) and not self.committed(word_address(raw_b))
        b = dict(raw_b,valid=False) if input_wait or parameter_wait else raw_b
        grant = self.held_owner if self.held_valid else int(bool(b['valid'] and
                                                               (not a['valid'] or self.prefer_b)))
        selected = b if grant else a
        recipient = self.owner if self.active else grant
        rsp_ready = bool(engine.pd_active) if recipient else bool(a['rsp_ready'])
        response = bool(self.pending_early or self.valid)
        data = (self.memory_data if self.read_pending else 0) if self.pending_early else self.data
        allowed = ((not self.pending or self.pending_early and grant and self.qualifies(b))
                   and not foreground and not self.host_valid)
        eligible = bool(allowed and self.active and self.owner and grant and b['valid']
                        and self.owner_read==b['read'])
        retire = bool(self.active and response and rsp_ready)
        available = not self.active or eligible and retire
        joined_valid = bool(available and selected['valid'])
        idle = not self.pending and not self.valid and not self.host_valid
        joined_ready = bool((idle or eligible and retire) and not foreground)
        fire = joined_valid and joined_ready
        dual_candidate = bool(stream and fire and grant and qualified_dma_read(selected))
        conflict = dual_candidate and (physical_word(self.mode,hword)//4096==
                                       physical_word(self.mode,word_address(selected))//4096)
        dual = dual_candidate and not conflict
        host_ready = bool(idle and (not (stream or background) or not joined_valid) or dual)
        host_fire = bool(host['valid'] and host_ready)
        physical = bool(host_fire or fire and selected['address']>>19==0x1400)
        command = host if host_fire and not dual else selected
        assert not (fire and host_fire) or dual
        self.current = dict(ready=bool(available and grant and joined_ready and not input_wait and not parameter_wait),
            valid=bool(response and (self.active or fire) and recipient),data=data,
            a_ready=bool(available and not grant and joined_ready),
            a_valid=bool(response and (self.active or fire) and not recipient),
            host_ready=host_ready,host_fire=host_fire,host=host,background=background,
            physical=physical,write=bool(physical and not command['read']),
            physical_address=command['address'] if host_fire and not dual else word_address(command),
            physical_data=command['data'],mask=command['mask'] if host_fire and not dual or not grant else 15,
            fire=fire,selected=selected,grant=grant,recipient=recipient,rsp_ready=rsp_ready,
            retire=retire,available=available,joined_valid=joined_valid,joined_ready=joined_ready,
            b=b,blocked=bool(raw_b['valid'] and input_wait),
            parameter_blocked=bool(raw_b['valid'] and parameter_wait),dual=dual,conflict=conflict)
        return self.current

    def tick(self,command,response_ready,cycle):
        c = self.current
        self.param_wait += int(c.get('parameter_blocked',False))
        self.conflicts += int(c.get('conflict',False))
        dual = c.get('dual',False)
        host = c['host']
        if c['host_fire'] and not host['read']:
            addr = host['address']
            if parameter_word(addr):
                assert addr==PARAMETER_WORD+self.parameter_prefix
                self.parameter_prefix+=1
                self.last_parameter_host=cycle
            elif shift_word(addr):
                assert addr==SHIFT_WORD+self.shift_prefix
                self.shift_prefix+=1
                self.last_shift_host=cycle
            elif addr==READY_WORD and host['data']==1:
                assert self.parameter_prefix==min(START_STREAM[self.mode],8448)
                self.stream_start=cycle
        if self.mode=='M0':
            super().tick(command,response_ready,cycle)
            return
        # The inherited port advances the single joined response state. A dual
        # host write commits separately and never changes the read-return tag.
        self.current = dict(c,physical_address=physical_word(self.mode,c['physical_address']))
        if dual:
            self.current['host_fire']=False
        super().tick(command,response_ready,cycle)
        if dual:
            pword=physical_word(self.mode,host['address'])
            assert pword//4096!=self.current['physical_address']//4096
            assert host['mask']==15 and not host['read']
            self.storage[pword]=host['data']
            self.host_writes+=1
            self.dual+=1
        self.current=c


def simulate(mode, pacing, case, program, initial, first_host, host_gap, compare=None, make_core=None):
    bootstrap = 128
    image, golden = m3.sr.frozen_image(case)
    image.update(enumerate(q16.q8.repack([image[i] for i in range(INPUT_WORDS)])))
    full_params = [image[PARAMETER_WORD+i] for i in range(8704)]
    for low, high in zip(full_params[8192::2],full_params[8193::2]):
        assert high == (0xffffffff if low >> 31 else 0)
    params = full_params[:8192] + full_params[8192::2]
    image.update((PARAMETER_WORD+i,value) for i,value in enumerate(params))
    # Guardians come from the same task's frozen image, while control values
    # are the actual host program (including the new task/parameter epoch).
    early = [(i,image[i]) for i in range(bootstrap)]
    early += [(addr,image[addr] if addr < 131008 else data) for addr,data in initial]
    loaded = [(PARAMETER_WORD+i,value) for i,value in enumerate(params)]
    loaded += [(i,image[i]) for i in range(SHIFT_WORD,SHIFT_WORD+64)]
    loaded.insert(START_STREAM[mode], (READY_WORD,1))
    late = [(i,image[i]) for i in range(bootstrap,INPUT_WORDS)]
    host_writes = early + loaded + late
    w = q16.q8.Wrapper64(case, True)
    w.core = core = make_core(case) if make_core else q16.Core(case,'Q16+PF2')
    w.parameter_limit = len(params)*2
    w.memory = mem = BankPort(w,mode)
    due = program[0]['start']
    i = h = retired = 0
    accepted = False
    first_mac = last_emit = final_ack = param_ready = None
    outstanding = None
    read_words = []
    descriptors = []
    differences = []
    background_during_mac = dma_write_handoffs = 0
    for cycle in range(70000):
        shared, cpu, host = (m3.sr.idle_cpu() for _ in range(3))
        if i < len(program) and not accepted and cycle >= due:
            command = program[i]
            endpoint = shared if command['bus']=='shared_cpu' else cpu
            endpoint.update({key:command[key] for key in ('read','address','data','mask')},valid=1)
        if h < len(host_writes) and cycle >= first_host and (
                h < len(early) or mem.parameter_request is not None and cycle >= mem.parameter_request + host_gap):
            address, data = host_writes[h]
            host.update(valid=1, read=0, address=address, data=data, mask=15)
        mem.context(dict(shared=shared,host=host,host_rsp_ready=1))
        c = w.comb(cpu)
        m = c['memory']
        if i < len(program):
            shared_bus = program[i]['bus']=='shared_cpu'
            endpoint = shared if shared_bus else cpu
            accepted |= bool(endpoint['valid'] and (m['a_ready'] if shared_bus else c['cpu_ready']))
            if accepted and (m['a_valid'] if shared_bus else c['cpu_valid']):
                if shared_bus and program[i]['read'] and program[i]['address']==BASE+4*READY_WORD:
                    assert m['data']==1, ('CPU observed unpublished stream doorbell',cycle)
                if compare is not None and cycle != program[i]['response'] and len(differences)<12:
                    differences.append((cycle,'cpu_response',i,program[i]['response']))
                accepted = False
                i += 1
                if i < len(program):
                    due = cycle + program[i]['gap']
                    if pacing == 'fixed_cpu':
                        due = max(due,program[i]['start'])
        if m['host_fire']:
            h += 1
            if m['physical_address']==READY_WORD and m['physical_data']==1:
                param_ready = cycle
            background_during_mac += int(m['background'] and core.state==7 and core.inner>=0)
        if core.state==7 and core.inner>=0 and first_mac is None:
            first_mac = cycle
        if core.comb(c['core_in'])['quant']:
            last_emit = cycle
        if c['core_in']['layer_start']:
            assert core.parameter_count==16896 and core.shift_count==128
        if c['launch']:
            descriptors.append(dict(cycle=cycle,kind=w.load_kind,**c['launch']))
        if m['valid'] and m['rsp_ready']:
            assert outstanding is not None
            if outstanding['read']:
                index = (outstanding['address']-BASE)//4
                assert m['data'] == image[index]
                read_words.append(index)
            elif outstanding['address']==BASE+4*(16384+12671):
                final_ack = cycle
            outstanding = None
        if m['fire'] and m['grant']:
            assert m['physical'] and outstanding is None
            outstanding = m['selected']
            assert outstanding['address']>>19==0x1400
            dma_write_handoffs += int(not outstanding['read'] and m['valid'] and m['rsp_ready'])
        if compare is not None and cycle in compare and len(differences)<12:
            row = compare[cycle]
            checks = dict(physical_accept=int(m['physical']), physical_write=int(m['write']),
                          dma_pd_count=w.engine.pd_count)
            if m['physical']:
                checks['live_addr'] = m['physical_address']
                if m['write']:
                    checks['live_wdata'] = m['physical_data']
            differences.extend((cycle,key,value,row[key]) for key,value in checks.items() if value!=row[key])
        for identity, value in w.tick(cpu,c,cycle):
            assert identity==retired and golden[identity]==value
            retired += 1
        if final_ack is not None:
            break
    assert final_ack is not None and h==len(host_writes) and mem.prefix==INPUT_WORDS
    assert mem.host_writes==11690 and mem.parameter_prefix==8448 and mem.shift_prefix==64
    if mode!='M0':
        assert mem.stream_start==param_ready
        if pacing=='response_relative':
            assert mem.dual>0
    assert (mem.reads,mem.writes,len(descriptors),retired) == (3232+len(params),12672,52,25344)
    assert sorted(read_words) == list(range(INPUT_WORDS)) + list(range(PARAMETER_WORD,PARAMETER_WORD+len(params))) + list(range(SHIFT_WORD,SHIFT_WORD+64))
    for index, (_, address, word) in enumerate(mem.commits):
        assert address==BASE+4*(16384+index)
        assert word==(golden[2*index]&65535)|((golden[2*index+1]&65535)<<16)
    commit = mem.commits[-1][0]
    return dict(mode=mode,pacing=pacing,case=case+1,first_mac=first_mac,last_emit=last_emit,
                final_physical_commit=commit,final_ack=final_ack,cold_cycles=commit+1,
                host_writes=mem.host_writes,host_payload=mem.host_writes-10,dma_reads=mem.reads,
                dma_writes=mem.writes,descriptors=len(descriptors),ordered_outputs=retired,
                last_input_commit=mem.last_input,parameter_ready_commit=param_ready,
                background_writes=mem.late_writes,background_during_mac=background_during_mac,
                input_dma_wait=mem.input_wait_cycles,dma_write_handoffs=dma_write_handoffs,
                dual_accept_cycles=mem.dual, same_bank_conflict_cycles=mem.conflicts,
                parameter_uncommitted_wait=mem.param_wait,
                parameter_host_last=mem.last_parameter_host,
                shift_host_last=mem.last_shift_host,
                descriptor_trace=descriptors,differences=differences)


def batch(mode,pacing,first,last,program,initial,start,gap):
    staged.patch_parameter_limit()
    return [simulate(mode,pacing,case,program,initial,start,gap) for case in range(first,last)]


def save(name,value):
    (REPORT/name).write_text(json.dumps(value,indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--calibrate',action='store_true')
    args = parser.parse_args()
    staged.patch_parameter_limit()
    program,initial,start,gap,native = load_observation()
    physical = [physical_word('I',word) for word in range(131072)]
    assert len(set(physical))==len(physical) and all(physical[word]==word for word in
        (0,16383,16384,32767,40960,41216,41472,59392,59456,READY_WORD))
    calibration = simulate('M0','response_relative',0,program,initial,start,gap,native)
    actual = {k:calibration[k] for k in ANCHORS}
    match = actual==ANCHORS and not calibration['differences']
    save('model-calibration.json',dict(passed=match,expected=ANCHORS,actual=calibration,
                                      native_trace=str(TRACE.relative_to(ROOT))))
    print(actual,calibration['differences'],flush=True)
    if not match:
        raise SystemExit('Native M0 calibration mismatch')
    if args.calibrate:
        return
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(batch,mode,pacing,first,first+3,program,initial,start,gap)
              for pacing in PACINGS for mode in START_STREAM for first in range(0,12,3)]
        rows=[r for job in jobs for r in job.result()]
    totals = {pacing:{mode:sum(r['cold_cycles'] for r in rows if r['mode']==mode and r['pacing']==pacing)
                      for mode in START_STREAM} for pacing in PACINGS}
    relative=totals['response_relative']
    assert relative['M0']==544164
    order=sorted((mode for mode in ('N','I') if relative[mode]<relative['M0']),
                 key=lambda mode:(relative[mode],('N','I').index(mode)))
    save('model-results.json',dict(passed=True,totals=totals,cycle_rank=order,
                                  model_winner=order[0] if order else None,hardware_selection=None,
                                  clock_hz=150000000,rows=rows))
    print(totals,order,flush=True)


if __name__=='__main__':
    main()
