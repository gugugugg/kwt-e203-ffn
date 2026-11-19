"""Causal cold-window screen for one fixed four-row datapath."""
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_r4f2_q8'
OBS = REPORT / 'received/observation/native-evidence' / REPORT.relative_to(ROOT) / 'observation'
spec = importlib.util.spec_from_file_location('retirement_model', ROOT / 'scripts/m3_retire/screen.py')
retire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retire)
m3 = retire.m3
signed, rne = m3.sr.signed, m3.r3o.rne
MODES = ('M0', 'SERIAL64', 'Q8')
PACES = ('response_relative', 'fixed_cpu')


class Output:
    def reset(self):
        self.groups = [None, None]
        self.ready = [False, False]
        self.banks = [[[None] * 128 for _ in range(8)] for _ in range(2)]
        self.held, self.pending = [], []
        self.retired = self.reads = self.writes = 0
        self.peak = [0, 0]
        self.group_ready = []
        self.group_freed = []

    def acquire(self, group):
        assert self.groups[group % 2] is None
        self.groups[group % 2] = group
        self.banks[group % 2] = [[None] * 128 for _ in range(8)]

    def write(self, group, words):
        generation = group % 2
        assert self.groups[generation] == group and not self.ready[generation]
        touched = set()
        for index, value in words:
            row, col = divmod(index, 256)
            assert row // 4 == group
            bank, address = 2 * (row % 4) + col % 2, col // 2
            assert bank not in touched and self.banks[generation][bank][address] is None
            touched.add(bank)
            self.banks[generation][bank][address] = (index, value)
            self.writes += 1

    def complete(self, group, cycle):
        generation = group % 2
        assert self.groups[generation] == group
        assert all(cell is not None for bank in self.banks[generation][:8 if group < 24 else 6] for cell in bank)
        self.ready[generation] = True
        self.group_ready.append(cycle)

    def comb(self, item, single, pair):
        pop = 2 if pair and len(self.held) >= 2 else int(bool(single and self.held))
        index = item + len(self.held) + len(self.pending)
        group = index // 1024
        space = 4 - len(self.held) - len(self.pending) + pop
        available = index < 25344 and self.groups[group % 2] == group and self.ready[group % 2]
        return pop, index, min(space, 2, 256 - index % 256) if available else 0

    def tick(self, control, cycle):
        pop, index, count = control
        popped = self.held[:pop]
        self.held = self.held[pop:] + self.pending
        self.pending = []
        for pos in range(index, index + count):
            row, col = divmod(pos, 256)
            group = row // 4
            word = self.banks[group % 2][2 * (row % 4) + col % 2][col // 2]
            assert word is not None and word[0] == pos
            self.pending.append(word)
            self.reads += 1
        for identity, _ in popped:
            assert identity == self.retired
            self.retired += 1
            if self.retired % 1024 == 0 or self.retired == 25344:
                group = identity // 1024
                assert self.groups[group % 2] == group and self.ready[group % 2]
                assert all(word[0] // 1024 != group for word in self.held + self.pending)
                self.groups[group % 2], self.ready[group % 2] = None, False
                self.group_freed.append(cycle)
        reserved = len(self.held) + len(self.pending)
        assert reserved <= 4
        self.peak[0] = max(self.peak[0], len(self.held))
        self.peak[1] = max(self.peak[1], reserved)
        return popped


class Core64:
    def __init__(self, case, wide):
        _, self.weights, self.bias, self.shifts = m3.r3o.vectors(case)
        self.wide = wide
        self.queue = Output()
        self.cycle = 0
        self.reset()
        self.state = 1

    def reset(self):
        self.state = self.row = self.tile = self.lane = self.inner = self.emit_row = self.item = self.chunk = 0
        self.input_count = self.parameter_count = self.shift_count = 0
        self.input_writes = self.input_write_beats = 0
        self.input_owner = [None, None]
        self.input_banks = [[[None] * 64 for _ in range(4)] for _ in range(2)]
        self.input_q = self.operands = self.bias_return = None
        self.acc, self.shift, self.products, self.seeds = ([0] * 64 for _ in range(4))
        self.commits = self.input_overlap = self.output_wait = 0
        self.input_ready_cycles = []
        self.queue.reset()

    def complete(self):
        return self.input_count >= min(99, self.row + 4) * 64

    def capacity(self, kind):
        if kind != 0:
            return self.state == 2 and kind in (1, 5)
        group = self.input_count // 256
        return (self.state >= 3 and self.input_count < 6336 and
                group <= self.row // 4 + 1 and self.input_owner[group % 2] in (None, group))

    def comb(self, inp):
        out = self.queue.comb(self.item, inp.get('out_ready'), inp.get('out_pair_ready'))
        return dict(out=out, quant=self.state == 8)

    def seed(self, row, col, tile):
        lane = row * 16 + col
        assert self.seeds[lane] == 0
        column = tile * 16 + col
        self.acc[lane] = signed(self.bias[column], 36)
        self.shift[lane] = self.shifts[column]
        self.seeds[lane] = 1

    def tick(self, inp, control):
        if inp.get('reset'):
            self.reset()
            return []
        cycle = self.cycle
        old_state = self.state
        group = self.row // 4
        valid = min(4, 99 - self.row)
        bank_generation = group % 2
        complete = self.complete()
        output_available = self.queue.groups[bank_generation] is None
        popped = self.queue.tick(control['out'], cycle)
        if inp.get('layer_start'):
            self.queue.reset()
        read = None
        if old_state == 6 and complete:
            read = 0
        elif old_state == 7:
            if self.inner < 62:
                read = self.inner + 2
            if self.inner >= 0:
                for row, token in enumerate(self.operands):
                    identity, value = token
                    assert identity == (self.row + row) * 64 + self.inner
                    lane = row * 16
                    weight = self.inner * 256 + self.tile * 16
                    for col in range(16):
                        self.acc[lane+col] = signed(self.acc[lane+col] + value*self.weights[weight+col], 36)
                        self.products[lane+col] += 1
            if self.inner < 63:
                self.operands = self.input_q
        if read is not None:
            assert self.input_owner[bank_generation] == group
            self.input_q = [self.input_banks[bank_generation][row][read] for row in range(valid)]
            assert all(token is not None for token in self.input_q)
        if inp.get('load'):
            kind = inp['load_kind']
            count = 2 if inp.get('load_pair') and kind != 5 else 1
            attr = {0:'input_count', 1:'parameter_count', 5:'shift_count'}[kind]
            old_count = getattr(self, attr)
            assert inp['load_address'] == old_count
            if kind == 0:
                touched = set()
                for offset in range(count):
                    target, local = divmod(old_count + offset, 256)
                    k, row = divmod(local, 4 if target < 24 else 3)
                    gen = target % 2
                    assert self.input_owner[gen] in (None, target) and (read is None or gen != bank_generation)
                    assert (gen,row) not in touched
                    if self.input_owner[gen] is None:
                        self.input_owner[gen] = target
                        self.input_banks[gen] = [[None]*64 for _ in range(4)]
                    touched.add((gen,row))
                    assert self.input_banks[gen][row][k] is None
                    self.input_banks[gen][row][k] = ((4*target+row)*64+k, signed(inp['input_word'] >> (16*offset) & 65535,16))
                self.input_writes += count
                self.input_write_beats += 1
                self.input_overlap += int(read is not None)
                if (old_count + count) % 256 == 0 or old_count + count == 6336:
                    self.input_ready_cycles.append(cycle)
            setattr(self, attr, old_count + count)
        if old_state == 0:
            self.state = 1
        elif old_state == 1 and inp.get('start'):
            self.parameter_count = self.shift_count = 0
            self.state = 2
        elif old_state == 2 and inp.get('layer_start'):
            self.state = 15
        elif old_state == 15:
            if complete and output_available:
                self.queue.acquire(group)
                self.state = 3
            elif complete:
                self.output_wait += 1
        elif old_state == 3:
            self.chunk = 0
            self.state = 4 if self.row == 0 else 6
        elif old_state == 4:
            self.bias_return = (0, self.chunk)
            self.state = 5
        elif old_state == 5:
            assert self.bias_return == (0,self.chunk)
            for row in range(valid):
                for col in (2*self.chunk,2*self.chunk+1):
                    self.seed(row,col,0)
            if self.chunk == 7:
                self.state = 6
            else:
                self.chunk += 1
                self.state = 4
        elif old_state == 6 and complete:
            self.inner, self.state = -1, 7
        elif old_state == 7:
            if self.inner == 63:
                self.emit_row = self.lane = 0
                self.state = 8
                if self.tile != 15 or group != 24:
                    self.bias_return = ((self.tile+1)%16,0)
                if self.tile == 15:
                    self.input_owner[bank_generation] = None
            else:
                self.inner += 1
        elif old_state == 8:
            rows = range(valid) if self.wide else (self.emit_row,)
            last = self.wide or self.emit_row == valid - 1
            target = (self.tile+1)%16
            has_next = self.tile != 15 or group != 24
            next_valid = min(4,99-(self.row+4 if self.tile==15 else self.row))
            words = []
            for row in rows:
                for col in (self.lane,self.lane+1):
                    lane = row*16+col
                    assert self.products[lane] == 64 and self.seeds[lane] == 1
                    words.append(((self.row+row)*256 + self.tile*16+col, rne(self.acc[lane],self.shift[lane])))
                    self.products[lane] = self.seeds[lane] = 0
                    if has_next and row < next_valid:
                        assert self.bias_return == (target,self.lane//2)
                        self.seed(row,col,target)
            self.queue.write(group,words)
            self.commits += 1
            if not last:
                self.emit_row += 1
            else:
                self.emit_row = 0
                if self.lane < 14:
                    self.lane += 2
                    if has_next:
                        self.bias_return = (target,self.lane//2)
                elif self.tile < 15:
                    self.tile += 1
                    self.state = 6
                else:
                    self.queue.complete(group,cycle)
                    self.state = 14
        elif old_state == 14:
            if group == 24:
                self.state = 12
            else:
                self.row += 4
                self.tile = self.lane = 0
                self.state = 15
        if popped:
            self.item += len(popped)
            if self.item == 25344:
                self.item -= len(popped)
                self.state = 0
                self.input_count = self.parameter_count = self.shift_count = 0
        return popped


class Wrapper64(m3.StreamWrapper):
    def __init__(self, case, wide):
        super().__init__('M3', case)
        self.core = Core64(case, wide)

    def tick(self, cpu, control, cycle):
        self.core.cycle = cycle
        return super().tick(cpu,control,cycle)


def repack(words):
    samples = [part for word in words for part in (word & 65535, word >> 16)]
    packed = [samples[row*64 + k] for group in range(0,99,4)
              for k in range(64) for row in range(group,min(group+4,99))]
    return [lo | hi << 16 for lo, hi in zip(packed[::2],packed[1::2])]


def program(commands):
    """Reuse measured per-command gaps at matching firmware control-flow edges."""
    out = list(commands[:11])
    first, second, first_write, steady_read, steady_write = [commands[i:i+4] for i in (11,15,19,23,27)]
    last_write = commands[-3:]
    def transfer(gaps, absolute, base, words, direction, extra=0):
        for i, (cmd, at, data) in enumerate(zip(gaps,absolute,(base,words,direction,0))):
            assert cmd['address'] == (0x40,0x44,0x48,0x50)[i]
            out.append(dict(cmd,data=data,start=at['start'],gap=cmd['gap']+(extra if i==0 else 0)))
    transfer(first,first,0xa0000000,128,1)
    for group in range(25):
        row = 4*group
        if group < 24:
            previous_group = (row+4)//3
            at = 15 + (previous_group-1)*8
            transfer(second if group==0 else steady_read,commands[at:at+4],
                     0xa0000000+(row+4)*128,min(4,99-row-4)*32,1)
        at = 19+(row//3)*8 if group<24 else len(commands)-3
        template = first_write if group==0 else steady_write if group<24 else last_write
        transfer(template,commands[at:at+len(template)],0xa0010000+row*512,min(4,99-row)*128,2)
    return out


def simulate(mode,pacing,case,prefix,commands,prior,compare=None):
    if mode == 'M0':
        row = retire.simulate('R4+F2',pacing,case,prefix,commands,prior,compare)
        row['mode'] = 'M0'
        return row
    wrapper = Wrapper64(case,mode=='Q8')
    run = retire.widened(m3.simulate, [
        ('wrapper = StreamWrapper(mode, case)','wrapper = candidate_wrapper'),
        ('12672,68,25344,33792,528,6336','12672,52,25344,25600,400,6336'),
    ])
    run.__globals__.update(candidate_wrapper=wrapper,repack=repack)
    row = run('M3',pacing,case,prefix,commands,prior)
    core = wrapper.core
    q = core.queue
    assert (q.reads,q.writes,len(q.group_ready),len(q.group_freed),len(core.input_ready_cycles)) == (25344,25344,25,25,25)
    assert core.commits == (3200 if mode=='Q8' else 12672)
    row.update(mode=mode,quant_commit_cycles=core.commits,output_macro_reads=q.reads,
               output_macro_writes=q.writes,output_generation_wait=core.output_wait,
               concurrent_input_macro_reads_and_writes=core.input_overlap,
               output_group_ready=q.group_ready,output_group_freed=q.group_freed,
               input_group_ready=core.input_ready_cycles)
    return row


def save(name, value):
    (REPORT/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def main():
    m3.OBS = OBS
    prefix, commands, prior = m3.read_program()
    rows = {}
    for row in m3.trace_rows(OBS/'events.csv'):
        row.update({key.replace('.','_'):value for key,value in row.items() if '.' in key})
        rows[row['cycle']] = row
    base = simulate('M0',PACES[0],0,prefix,commands,prior,rows)
    expected = dict(first_mac=21159,last_row0_emit=70626,final_physical_commit=70886,final_ack=70887,
                    cold_cycles=70887,paired_reads=8448,consecutive_paired_reads=7871,
                    fifo_direct_words=4852,dma_write_handoffs=7904,stalled_by_row=[0,0,1856])
    actual = {key:base[key] for key in expected}
    passed = actual==expected and not base['divergence']
    save('calibration.json',dict(passed=passed,expected=expected,actual=actual,model=base))
    print('R4F2_CALIBRATION',passed,actual,base['divergence'][:2],flush=True)
    if not passed:
        raise RuntimeError('R4+F2 calibration differs')
    adapted = program(commands)
    save('cpu-program.json',dict(frozen_r4f2_commands=commands,q8_commands=adapted,
         relative='Measured MMIO gaps at matching first-input, loop-input, loop-output and final-output firmware edges.',
         fixed='Issue floor mapped to the baseline descriptor covering the same starting row.'))
    results = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(simulate,mode,pace,case,prefix,commands if mode=='M0' else adapted,prior)
                   for pace in PACES for case in range(12) for mode in MODES]
        for job in pending:
            row=job.result()
            results.append(row)
            print('Q8_MODEL',row['mode'],row['pacing'],row['case'],row['cold_cycles'],flush=True)
    totals={pace:{mode:sum(r['cold_cycles'] for r in results if r['pacing']==pace and r['mode']==mode)
                  for mode in MODES} for pace in PACES}
    primary=totals[PACES[0]]
    selected='Q8' if primary['Q8']<min(850644,primary['M0'],primary['SERIAL64']) else None
    save('model-selection.json',dict(passed=True,selected=selected,cycles_total=totals,results=results,
        model_only=True,projected_throughput={p:{m:1800000000/c for m,c in t.items()} for p,t in totals.items()}))
    print('Q8_SELECTION',selected,totals,flush=True)


if __name__=='__main__':
    main()
