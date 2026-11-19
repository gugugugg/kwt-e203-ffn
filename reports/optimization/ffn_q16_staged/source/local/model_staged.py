"""Replay Q16 CPU dependencies with an independently scheduled shared port."""
import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/q8_q16'))
import model_q16 as q16

m3 = q16.m3
REPORT = ROOT / 'reports/optimization/ffn_q16_staged'
TRACE = REPORT / ('received/observation/native-evidence/reports/optimization/'
                  'ffn_q16_staged/observation/events.csv')
MODES = {'M0': (3168, False), 'B32': (3168, True), 'S2': (256, False),
         'S2+B32': (256, True), 'S1+B32': (128, True)}
ANCHORS = dict(first_mac=21192, last_emit=48511, final_physical_commit=48898,
               final_ack=48899, cold_cycles=48899)
BASE = 0xa0000000
INPUT_WORDS = 3168
PARAMETER_WORD = 32768
SHIFT_WORD = 59392
READY_WORD = 131021
PARAMETER_REQUEST = 0xa007ff30


def load_observation():
    commands, host, pending, rows = [], [], {}, {}
    for row in m3.trace_rows(TRACE):
        cycle = row['cycle']
        rows[cycle] = row
        for bus in ('cpu', 'shared_cpu'):
            if row[bus+'_cmd_valid'] and bus not in pending:
                pending[bus] = dict(bus=bus, start=cycle, **{
                    key: row[bus+'_cmd_'+signal] for key, signal in
                    (('read','read'), ('address','addr'), ('data','wdata'), ('mask','wmask'))})
            if row[bus+'_cmd_valid'] and row[bus+'_cmd_ready']:
                pending[bus]['accept'] = cycle
            if row[bus+'_rsp_valid'] and row[bus+'_rsp_ready'] and bus in pending:
                commands.append(dict(pending.pop(bus), response=cycle))
        if row['host_cmd_valid'] and row['host_cmd_ready']:
            assert not row['host_cmd_read'] and row['host_cmd_wmask'] == 15
            host.append((cycle, row['host_cmd_addr'], row['host_cmd_wdata']))
    commands.sort(key=lambda command: command['start'])
    prior = 0
    for command in commands:
        command['gap'] = command['start'] - prior
        assert command['gap'] > 0
        prior = command['response']
    initial = [(addr,data) for _,addr,data in host[INPUT_WORDS:INPUT_WORDS+9]]
    parameter_cycle = host[INPUT_WORDS+9][0]
    request_cycle = next(c['accept'] for c in commands if c['address']==PARAMETER_REQUEST)
    assert (len(host), host[0][:2], host[-1][1:]) == (11946,(2,0),(READY_WORD,1))
    return commands, initial, host[0][0], parameter_cycle-request_cycle, rows


def patch_parameter_limit():
    # Reuse the stock transaction model, including the four-entry output queue.
    source = (ROOT / 'scripts/taskflow_study/transport.py').read_text()
    start = source.index('    def comb(self, cpu):', source.index('class Wrapper:'))
    end = source.index('    def tick(self, cpu, c, cycle):', start)
    from transport import Wrapper
    ns = dict(Wrapper.comb.__globals__)
    code = dedent(source[start:end]).replace('h == 2','h >= 2').replace('17408','self.parameter_limit')
    exec(compile(code, str(Path(__file__)), 'exec'), ns)
    Wrapper.comb = ns['comb']


class SharedPort(m3.FastMemory):
    def __init__(self, wrapper, staged):
        super().__init__(wrapper)
        self.staged = staged
        self.prefix = 0
        self.background_phase = False
        self.parameter_request = None
        self.late_writes = self.input_wait_cycles = 0
        self.last_input = None

    def comb(self):
        ext, w = self.external, self.wrapper
        e = w.engine
        b = e.commands(w.core.capacity(w.load_kind), len(w.core.queue.held) >= 2)['memory']
        a, host = ext['shared'], ext['host']
        background = (self.staged and self.background_phase and host['valid']
                      and not host['read'] and host['mask'] == 15 and host['address'] == self.prefix
                      and self.prefix < INPUT_WORDS)
        foreground = host['valid'] and not background
        input_wait = (self.staged and m3.input_read(b) and self.prefix < INPUT_WORDS
                      and self.prefix // 128 <= ((b['address']-BASE)//4)//128)
        blocked = bool(b['valid'] and input_wait)
        if input_wait:
            b = dict(b, valid=False)
        grant = self.held_owner if self.held_valid else int(bool(b['valid'] and (not a['valid'] or self.prefer_b)))
        selected = b if grant else a
        recipient = self.owner if self.active else grant
        rsp_ready = bool(e.pd_active) if recipient else bool(a['rsp_ready'])
        response = bool(self.pending_early or self.valid)
        data = (self.memory_data if self.read_pending else 0) if self.pending_early else self.data
        allowed = ((not self.pending or self.pending_early and grant and self.qualifies(b))
                   and not foreground and not self.host_valid)
        eligible = bool(allowed and self.active and self.owner and grant and b['valid']
                        and self.owner_read == b['read'])
        retire = bool(self.active and response and rsp_ready)
        available = not self.active or eligible and retire
        joined_valid = bool(available and selected['valid'])
        idle = not self.pending and not self.valid and not self.host_valid
        joined_ready = bool((idle or eligible and retire) and not foreground)
        fire = joined_valid and joined_ready
        host_ready = bool(idle and (not background or not joined_valid))
        host_fire = bool(host['valid'] and host_ready)
        physical = bool(host_fire or fire and selected['address'] >> 19 == 0x1400)
        command = host if host_fire else selected
        assert not (fire and host_fire)
        self.current = dict(
            ready=bool(available and grant and joined_ready and not input_wait),
            valid=bool(response and (self.active or fire) and recipient), data=data,
            a_ready=bool(available and not grant and joined_ready),
            a_valid=bool(response and (self.active or fire) and not recipient),
            host_ready=host_ready, host_fire=host_fire, host=host, background=background,
            physical=physical, write=bool(physical and not command['read']),
            physical_address=command['address'] if host_fire else command['address']>>2 & 0x1ffff,
            physical_data=command['data'], mask=command['mask'] if host_fire or not grant else 15,
            fire=fire, selected=selected, grant=grant, recipient=recipient, rsp_ready=rsp_ready,
            retire=retire, available=available, joined_valid=joined_valid, joined_ready=joined_ready,
            b=b, blocked=blocked)
        return self.current

    def tick(self, command, response_ready, cycle):
        c = self.current
        self.input_wait_cycles += int(c['blocked'])
        if c['host_fire'] and c['write']:
            addr = c['physical_address']
            if addr < INPUT_WORDS:
                assert addr == self.prefix
                self.prefix += 1
                self.last_input = cycle
                self.late_writes += int(c['background'])
            elif addr == READY_WORD and c['physical_data'] == 1:
                self.background_phase = True
        if c['fire'] and not c['grant'] and not c['selected']['read']:
            if c['selected']['address'] == PARAMETER_REQUEST:
                self.parameter_request = cycle
        super().tick(command,response_ready,cycle)


def simulate(mode, pacing, case, program, initial, first_host, host_gap, compare=None):
    bootstrap, compact = MODES[mode]
    image, golden = m3.sr.frozen_image(case)
    image.update(enumerate(q16.q8.repack([image[i] for i in range(INPUT_WORDS)])))
    params = [image[PARAMETER_WORD+i] for i in range(8704)]
    if compact:
        for low, high in zip(params[8192::2],params[8193::2]):
            assert high == (0xffffffff if low >> 31 else 0)
        params = params[:8192] + params[8192::2]
        image.update((PARAMETER_WORD+i,value) for i,value in enumerate(params))
    # Guardians come from the same task's frozen image, while control values
    # are the actual host program (including the new task/parameter epoch).
    early = [(i,image[i]) for i in range(bootstrap)]
    early += [(addr,image[addr] if addr < 131008 else data) for addr,data in initial]
    loaded = [(PARAMETER_WORD+i,value) for i,value in enumerate(params)]
    loaded += [(i,image[i]) for i in range(SHIFT_WORD,SHIFT_WORD+64)] + [(READY_WORD,1)]
    late = [(i,image[i]) for i in range(bootstrap,INPUT_WORDS)]
    host_writes = early + loaded + late
    w = q16.q8.Wrapper64(case, True)
    w.core = core = q16.Core(case,'Q16+PF2')
    w.parameter_limit = len(params)*2
    w.memory = mem = SharedPort(w,bool(late))
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
            if compact and endpoint is cpu and not cpu['read'] and cpu['address']==0x44 and cpu['data']==8704:
                cpu['data'] = len(params)
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
                descriptor_trace=descriptors,differences=differences)


def simulate_batch(mode, pacing, first, last, program, initial, start, gap):
    patch_parameter_limit()
    return [simulate(mode,pacing,case,program,initial,start,gap) for case in range(first,last)]


def save(name, value):
    (REPORT / name).write_text(json.dumps(value,indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--calibrate', action='store_true')
    args = parser.parse_args()
    patch_parameter_limit()
    program, initial, start, gap, native = load_observation()
    calibration = simulate('M0','response_relative',0,program,initial,start,gap,native)
    match = {k:calibration[k] for k in ANCHORS}==ANCHORS and not calibration['differences']
    save('model-calibration.json',dict(passed=match,expected=ANCHORS,actual=calibration))
    print({k:calibration[k] for k in ANCHORS},calibration['differences'],flush=True)
    if not match:
        raise SystemExit('Native calibration mismatch')
    if args.calibrate:
        return
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(simulate_batch,mode,pacing,first,first+3,program,initial,start,gap)
                   for pacing in ('response_relative','fixed_cpu') for mode in MODES for first in range(0,12,3)]
        results = [row for future in futures for row in future.result()]
    totals = {pacing:{mode:sum(r['cold_cycles'] for r in results if r['mode']==mode and r['pacing']==pacing)
                      for mode in MODES} for pacing in ('response_relative','fixed_cpu')}
    relative = totals['response_relative']
    assert relative['M0']==586788
    viable = [name for name in MODES if relative[name]<relative['M0']]
    winner = min(viable,key=lambda n:(relative[n],n.count('+'),list(MODES).index(n))) if viable else None
    save('model-selection.json',dict(passed=True,selected=winner,totals=totals,rows=results,
                                    period_hz=150000000,ordering='response_relative'))
    print(totals,winner,flush=True)


if __name__=='__main__':
    main()
