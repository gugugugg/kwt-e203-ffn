"""Select at most one hardware candidate using the observed Q8 cold task."""
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
NAME = 'ffn_q8_q16'
REPORT = ROOT / 'reports/optimization' / NAME
OBS = REPORT / 'received/observation/native-evidence' / REPORT.relative_to(ROOT) / 'observation'
sys.path.insert(0, str(ROOT / 'scripts/r4f2_q8'))
import model_q8 as q8

m3, retire, signed, rne = q8.m3, q8.retire, q8.signed, q8.rne
MODES = ('M0', 'Q16', 'Q16+PF2')
PACES = q8.PACES
ANCHORS = dict(first_mac=21192, first_output_commit=22377, last_emit=50861,
               final_physical_commit=51248, final_ack=51249, cold_cycles=51249)


class Output16(q8.Output):
    """Four physical banks per row, two generations in the address."""
    def reset(self):
        super().reset()
        self.banks = [[None] * 128 for _ in range(16)]
        self.blocked_reads = self.odd_bank_wraps = self.pending_during_write = 0

    @staticmethod
    def location(index):
        row, col = divmod(index, 256)
        return 4 * (row % 4) + col % 4, ((row // 4) % 2) * 64 + col // 4

    def acquire(self, group):
        generation = group % 2
        assert self.groups[generation] is None
        self.groups[generation] = group
        self.ready[generation] = False
        for bank in self.banks:
            bank[generation*64:(generation+1)*64] = [None] * 64

    def write(self, group, words):
        assert self.groups[group%2] == group and not self.ready[group%2]
        touched = set()
        for index, value in words:
            assert index // 1024 == group
            bank, address = self.location(index)
            assert bank not in touched and self.banks[bank][address] is None
            self.banks[bank][address] = index, value
            touched.add(bank)
            self.writes += 1

    def complete(self, group, cycle):
        assert self.groups[group%2] == group
        lo = (group % 2) * 64
        assert all(entry is not None for bank in self.banks[:16 if group < 24 else 12]
                   for entry in bank[lo:lo+64])
        self.ready[group%2] = True
        self.group_ready.append(cycle)

    def comb(self, item, single, pair, commit_rows=0):
        pop, index, count = super().comb(item, single, pair)
        blocked = bool(count and (index // 256) % 4 < commit_rows)
        return pop, index, 0 if blocked else count, blocked, commit_rows

    def tick(self, control, cycle):
        pop, index, count, blocked, commit_rows = control
        self.blocked_reads += blocked
        self.odd_bank_wraps += count == 2 and index % 4 == 3
        self.pending_during_write += bool(commit_rows and self.pending)
        popped = self.held[:pop]
        self.held = self.held[pop:] + self.pending
        self.pending = []
        touched = set()
        for pos in range(index, index+count):
            bank, address = self.location(pos)
            assert bank not in touched and bank // 4 >= commit_rows
            word = self.banks[bank][address]
            assert word is not None and word[0] == pos
            self.pending.append(word)
            touched.add(bank)
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


class Core(q8.Core64):
    def __init__(self, case, mode):
        self.width = 2 if mode == 'M0' else 4
        self.pf2 = mode == 'Q16+PF2'
        super().__init__(case, True)
        if self.width == 4:
            self.queue = Output16()
            self.queue.reset()

    def reset(self):
        super().reset()
        self.shadow = [None] * 8
        self.weight_address = self.operand_weight_address = None
        self.prefetch_tiles = 0

    def initial_seed_needed(self):
        return self.row == 0

    def comb(self, inp):
        if self.width == 2:
            return super().comb(inp)
        rows = min(4, 99 - self.row) if self.state == 8 else 0
        out = self.queue.comb(self.item, inp.get('out_ready'), inp.get('out_pair_ready'), rows)
        return dict(out=out, quant=bool(rows))

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
        read_tile = self.tile
        if old_state == 6 and complete:
            read = 0
        elif old_state == 7:
            if self.inner < 62:
                read = self.inner + 2
            if self.inner >= 0:
                assert self.operand_weight_address == (self.tile, self.inner)
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
                self.operand_weight_address = self.weight_address
        elif old_state == 8 and self.pf2 and self.tile < 15 and self.lane >= 8:
            read_tile = self.tile + 1
            read = (self.lane - 8) // 4
            if read == 1:
                self.operands = self.input_q
                self.operand_weight_address = self.weight_address
        if read is not None:
            self.weight_address = read_tile, read
            assert self.input_owner[bank_generation] == group
            self.input_q = [self.input_banks[bank_generation][row][read] for row in range(valid)]
            assert all(token is not None for token in self.input_q)
        self.accept_load(inp, read is not None, bank_generation, cycle)
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
            self.state = 4 if self.initial_seed_needed() else 6
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
            if self.width == 4 and (self.tile < 15 or group < 24):
                if 56 <= self.inner <= 63:
                    pair = self.inner - 56
                    target = (self.tile + 1) % 16
                    assert self.bias_return == (target, pair)
                    self.shadow[pair] = tuple((self.bias[target*16 + column], self.shifts[target*16 + column])
                                              for column in (2*pair, 2*pair + 1))
                if 55 <= self.inner <= 62:
                    self.bias_return = ((self.tile + 1) % 16, self.inner - 55)
            if self.inner == 63:
                self.emit_row = self.lane = 0
                self.state = 8
                if self.width == 2 and (self.tile != 15 or group != 24):
                    self.bias_return = ((self.tile+1)%16,0)
                if self.tile == 15:
                    self.input_owner[bank_generation] = None
            else:
                self.inner += 1
        elif old_state == 8:
            target = (self.tile + 1) % 16
            has_next = self.tile < 15 or group < 24
            next_valid = min(4, 99 - (self.row + 4 if self.tile == 15 else self.row))
            words = []
            for row in range(valid):
                for col in range(self.lane, self.lane + self.width):
                    lane = row*16 + col
                    assert self.products[lane] == 64 and self.seeds[lane] == 1
                    words.append(((self.row+row)*256 + self.tile*16+col, rne(self.acc[lane],self.shift[lane])))
                    self.products[lane] = self.seeds[lane] = 0
                    if has_next and row < next_valid:
                        if self.width == 4:
                            bias, shift = self.shadow[col//2][col%2]
                            assert (bias, shift) == (self.bias[target*16+col], self.shifts[target*16+col])
                            self.acc[lane] = signed(bias, 36)
                            self.shift[lane] = shift
                            self.seeds[lane] = 1
                        else:
                            assert self.bias_return == (target,self.lane//2)
                            self.seed(row,col,target)
            self.queue.write(group, words)
            self.commits += 1
            if self.lane + self.width < 16:
                self.lane += self.width
                if has_next and self.width == 2:
                    self.bias_return = (target, self.lane//2)
            elif self.tile < 15:
                self.tile += 1
                if self.pf2:
                    self.state, self.inner = 7, 0
                    self.prefetch_tiles += 1
                else:
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
        return self.retire(popped)

    def accept_load(self, inp, reading, bank_generation, cycle):
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
                    assert self.input_owner[gen] in (None, target) and (not reading or gen != bank_generation)
                    assert (gen,row) not in touched
                    if self.input_owner[gen] is None:
                        self.input_owner[gen] = target
                        self.input_banks[gen] = [[None]*64 for _ in range(4)]
                    touched.add((gen,row))
                    assert self.input_banks[gen][row][k] is None
                    self.input_banks[gen][row][k] = ((4*target+row)*64+k, signed(inp['input_word'] >> (16*offset) & 65535,16))
                self.input_writes += count
                self.input_write_beats += 1
                self.input_overlap += int(reading)
                if (old_count + count) % 256 == 0 or old_count + count == 6336:
                    self.input_ready_cycles.append(cycle)
            setattr(self, attr, old_count + count)

    def retire(self, popped):
        if popped:
            self.item += len(popped)
            if self.item == 25344:
                self.item -= len(popped)
                self.state = 0
                self.input_count = self.parameter_count = self.shift_count = 0
        return popped


def simulate(mode, pacing, case, prefix, commands, prior, compare=None):
    wrapper = q8.Wrapper64(case, True)
    wrapper.core = core = Core(case, mode)
    base = m3.simulate
    run = retire.widened(base, [
        ('wrapper = StreamWrapper(mode, case)', 'wrapper = candidate_wrapper'),
        ('12672,68,25344,33792,528,6336', '12672,52,25344,25600,expected_fill,6336'),
        ('emit_row=core.emit_row,lane=core.lane,', 'lane=core.lane,'),
        ('input_count=core.input_count, fifo_count=len(core.queue.fifo),', 'input_count=core.input_count,'),
        ('core_state=(10 if core.state == 7 and core.inner < 0 else core.state),',
         'core_state=(10 if core.state == 7 and core.inner < 0 else core.state),'),
        ("output_queue_pending_count=len(core.queue.pending), physical_accept=int(m['physical']))",
         """output_queue_pending_count=len(core.queue.pending), physical_accept=int(m['physical']),
                          output_queue_issue_count=cc['out'][2], output_queue_pop_count=cc['out'][0],
                          item=core.item)"""),
        ('active = e.pd_active', """active = e.pd_active
        writes = bool(m['fire'] and m['grant'] and not m['selected']['read'])
        candidate_wrapper.write_handoffs += int(writes and m['valid'] and m['rsp_ready'])"""),
    ])
    wrapper.write_handoffs = 0
    run.__globals__.update(candidate_wrapper=wrapper, repack=q8.repack, expected_fill=25 if core.pf2 else 400)
    result = run('M3', pacing, case, prefix, commands, prior, compare)
    queue = core.queue
    assert (queue.reads, queue.writes, len(queue.group_ready), len(queue.group_freed),
            len(core.input_ready_cycles), core.commits, core.prefetch_tiles) == (
                25344,25344,25,25,25,3200 if mode == 'M0' else 1600,375 if core.pf2 else 0)
    result.update(mode=mode, quant_commit_cycles=core.commits, pf2_tile_handoffs=core.prefetch_tiles,
        output_macro_reads=queue.reads, output_macro_writes=queue.writes, output_generation_wait=core.output_wait,
        blocked_result_reads=getattr(queue,'blocked_reads',0),
        accepted_pending_during_write=getattr(queue,'pending_during_write',0),
        dma_write_handoffs=wrapper.write_handoffs, output_group_ready=queue.group_ready,
        output_group_freed=queue.group_freed, input_group_ready=core.input_ready_cycles)
    return result


def mixed_reads():
    queue = Output16()
    queue.reset()
    # Leave generation 0 readable while new writes reserve generation 1.
    for group in (0, 1):
        queue.acquire(group)
        for row in range(4):
            for col in range(0,256,4):
                queue.write(group, [(group*1024+row*256+i, group*1024+row*256+i) for i in range(col,col+4)])
        queue.complete(group,0)
    item = 0
    for cycle in range(5000):
        single = (item < 3 or item == 255 or cycle % 17 == 8) and cycle % 7 != 2
        pair = item >= 3 and item != 255 and not single and cycle % 7 != 2
        control = queue.comb(item, single, pair, 4 if cycle % 13 == 7 else 0)
        popped = queue.tick(control, cycle)
        assert popped == [(i,i) for i in range(item,item+len(popped))]
        item += len(popped)
        if item == 2048:
            break
    assert item == 2048 and queue.odd_bank_wraps and queue.blocked_reads and queue.pending_during_write
    return dict(outputs=item, bank_wrap_pairs=queue.odd_bank_wraps,
                blocked_reads=queue.blocked_reads, captured_pending_on_commit=queue.pending_during_write)


def save(name, data):
    (REPORT/name).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')


def main():
    m3.OBS = OBS
    prefix, commands, prior = m3.read_program()
    rows = {}
    for row in m3.trace_rows(OBS/'events.csv'):
        row.update({key.replace('.','_'):value for key,value in row.items() if '.' in key})
        rows[row['cycle']] = row
    base = simulate('M0', PACES[0], 0, prefix, commands, prior, rows)
    actual = {key:base[key] for key in ANCHORS}
    passed = actual == ANCHORS and not base['divergence']
    save('calibration.json',dict(passed=passed,expected=ANCHORS,actual=actual,model=base))
    print('Q8_CALIBRATION',passed,actual,base['divergence'][:2],flush=True)
    if not passed:
        raise RuntimeError('Resolve calibration before screening')
    save('cpu-program.json',dict(commands=commands, prior_response=prior,
         relative='Measured Q8 MMIO response-to-request gaps.',
         fixed='Measured Q8 absolute request cycles as issue floors.'))
    directed = mixed_reads()
    results = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(simulate, mode, pace, case, prefix, commands, prior)
                for pace in PACES for case in range(12) for mode in MODES]
        for job in jobs:
            row = job.result()
            results.append(row)
            print('Q16_MODEL',row['mode'],row['pacing'],row['case'],row['cold_cycles'],flush=True)
    totals = {pace:{mode:sum(r['cold_cycles'] for r in results if r['pacing']==pace and r['mode']==mode)
                     for mode in MODES} for pace in PACES}
    assert all(totals[pace]['M0'] == 614988 for pace in PACES)
    eligible = [mode for mode in MODES[1:] if totals[PACES[0]][mode] < 600000]
    selected = min(eligible,key=lambda mode:totals[PACES[0]][mode]) if eligible else None
    save('model-selection.json',dict(passed=True,selected=selected,cycles_total=totals,results=results,
         model_only=True,directed_reads=directed,
         projected_throughput={p:{m:1800000000/c for m,c in t.items()} for p,t in totals.items()}))
    print('Q16_SELECTION',selected,totals,flush=True)


if __name__ == '__main__':
    main()
