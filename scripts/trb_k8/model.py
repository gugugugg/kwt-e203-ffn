"""Cycle model for boot-time G2 reuse on frozen T+R+B."""
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_trb_k8'
TRACE = REPORT / 'received/observation/native-evidence' / REPORT.relative_to(ROOT) / 'observation/events.csv'
spec = importlib.util.spec_from_file_location('trb', ROOT / 'scripts/sg_reuse/model_next.py')
trb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trb)
t, q16 = trb.t, trb.q16
BOOTSTRAP = {'M0': 256, 'K8-3': 384, 'K8-4': 512}
ANCHORS = dict(first_mac=1098, last_emit=32994, final_physical_commit=33261,
               final_ack=33262, cold_cycles=33262)


def observe():
    trb.TRACE = TRACE
    return trb.observation()


class ChainWrapper(q16.q8.Wrapper64):
    def __init__(self, case):
        super().__init__(case, True)
        self.chain = 0
        self.programmed = set()

    def comb(self, cpu):
        idle = t.m3.sr.idle_cpu
        internal = self.chain >= 2
        command = cpu
        if 2 <= self.chain <= 4:
            address, data = ((0x18, 1), (8, 1), (12, 0))[self.chain - 2]
            command = dict(idle(), valid=1, address=address, data=data, mask=15)
        elif self.chain == 5 or self.chain and cpu['read'] and cpu['address'] == 0x50:
            command = dict(idle(), valid=0)
        elif cpu['valid'] and not cpu['read'] and cpu['address'] == 0x48 and cpu['data'] == 3:
            command = dict(cpu, data=1)
        result = super().comb(command)
        result['inner_cpu'] = command
        result['chain_reply'] = internal and result['cpu_valid'] and result['pio_rsp_ready']
        if self.chain == 5:
            result['launch'] = dict(address=self.csr_address, words=self.csr_words, direction=0)
        if internal or command is not cpu and not command['valid']:
            result['cpu_ready'] = result['cpu_valid'] = False
        return result

    def tick(self, cpu, control, cycle):
        if self.chain == 0 and control['launch'] and cpu['data'] == 3:
            self.chain = 1
            self.programmed.clear()
        elif self.chain == 1:
            if self.programmed == {0x40, 0x44} and not self.engine.pd_active and self.core.layer_ready():
                self.chain = 2
            if control['csr_fire'] and not cpu['read']:
                self.programmed.add(cpu['address'])
        elif self.chain == 5:
            self.chain = 0
        elif control['chain_reply']:
            self.chain += 1
        return super().tick(control['inner_cpu'], control, cycle)

class StartupPort(trb.TailPort):
    def __init__(self, wrapper, mode, bootstrap):
        super().__init__(wrapper, mode)
        self.bootstrap = bootstrap

    def stream_address(self, word):
        return super().stream_address(word) or word == self.prefix < self.bootstrap

    def dual_read(self, command):
        return super().dual_read(command) or t.m3.input_read(command) and 0 <= t.word_address(command) < self.bootstrap

    def tick(self, command, response_ready, cycle):
        edge = self.current
        super().tick(command, response_ready, cycle)
        if edge['dual'] and not edge['background'] and 256 <= edge['host']['address'] < self.bootstrap:
            assert edge['host']['address'] == self.prefix
            self.prefix += 1
            self.last_input = cycle


def startup_host(early, loaded, late, image, bootstrap):
    bias, shift, mailbox, weights = loaded[:256], loaded[256:320], loaded[320], loaded[321:]
    assert mailbox == (t.READY_WORD, 1)
    words = early[:1] + early[bootstrap:] + [mailbox] + shift + bias + early[1:bootstrap] + weights + late
    return words, len(words)


def adapt(program, bootstrap):
    if bootstrap == 256:
        return program
    boundary = next(i for i, c in enumerate(program) if c['address'] == 12 and c['data'] == 512)
    head = [dict(c) for c in program[:boundary+1]]
    chain = next(i for i, c in enumerate(head) if c['address'] == 0x48 and c['data'] == 3)
    assert head[chain-1]['address'] == 0x44 and head[chain-1]['data'] == 256
    head[chain-1]['data'] = bootstrap
    head[-1]['data'] = 2 * bootstrap
    tail = [program[i:i+4] for i in range(boundary+1, len(program), 4)]
    inputs, outputs = {}, {}
    for desc in tail:
        assert [c['address'] for c in desc] == [0x40, 0x44, 0x48, 0x50][:len(desc)]
        if desc[2]['data'] == 1:
            inputs[(desc[0]['data'] - t.BASE) // 512] = desc
        else:
            assert desc[2]['data'] == 2
            outputs[(desc[0]['data'] - t.BASE - 65536) // 2048] = desc
    assert sorted(inputs) == list(range(2, 25)) and sorted(outputs) == list(range(25))
    order = ([inputs[3]] if bootstrap == 384 else []) + [outputs[0], outputs[1]]
    for group in range(4, 25):
        order.extend((inputs[group], outputs[group-2]))
    order.extend((outputs[23], outputs[24]))
    rebuilt = [dict(c) for desc in order for c in desc]
    rebuilt[0]['gap'] = tail[0][0]['gap']
    return head + rebuilt


class ScratchQueue(trb.ReuseQueue):
    def reset(self):
        super().reset()
        self.scratch = [[None] * 128 for _ in range(4)]
        self.scratch_reads = self.scratch_writes = 0

    @staticmethod
    def location(index):
        group, offset = divmod(index, 1024)
        row, col = divmod(offset, 256)
        if group == 2 and 112 <= col < 240:
            return 16 + col % 4, row * 32 + (col - 112) // 4
        return trb.ReuseQueue.location(index)

    def store_scratch(self, words):
        touched = set()
        for index, value in words:
            bank, addr = self.location(index)
            assert bank >= 16 and bank not in touched and self.scratch[bank-16][addr] is None
            self.scratch[bank-16][addr] = index, value
            touched.add(bank)
            self.scratch_writes += 1
            self.writes += 1

    def comb(self, item, single, pair, commit_rows=0):
        pop, index, count, blocked, rows = super().comb(item, single, pair, commit_rows)
        if count == 2 and index // 1024 == 2 and index % 256 in (111, 239):
            count = 1
        return pop, index, count, blocked, rows

    def tick(self, control, cycle):
        _, index, count, _, _ = control
        for pos in range(index, index + count):
            self.scratch_reads += self.location(pos)[0] >= 16
        self.banks.extend(self.scratch)
        popped = super().tick(control, cycle)
        del self.banks[16:]
        return popped

    def complete(self, group, cycle):
        if group != 2:
            super().complete(group, cycle)
            return
        assert self.groups[0] == group
        for index in range(2048, 3072):
            bank, address = self.location(index)
            entry = self.scratch[bank-16][address] if bank >= 16 else self.banks[bank][address]
            assert entry is not None and entry[0] == index
        self.ready[0] = True
        self.group_ready.append(cycle)


class K8Core(trb.ReuseCore):
    def __init__(self, case, bootstrap):
        self.bootstrap = bootstrap
        super().__init__(case)
        self.queue = ScratchQueue()
        self.queue.reset()

    def reset(self):
        super().reset()
        self.upper_owner = [None, None]
        self.upper_banks = [None, None]
        self.aux_pipe = [None, None]
        self.aux_write = None
        self.aux_issues = self.aux_executes = self.input_port_wait = 0
        self.physical_use = [None] * 4
        self.boot_load = False

    def successor_tile(self, group, tile):
        return 15 if (group, tile) == (2, 6) else super().successor_tile(group, tile)

    def predecessor_tile(self, group, tile):
        return 6 if (group, tile) == (2, 15) else super().predecessor_tile(group, tile)

    def layer_ready(self):
        return self.parameter_count == 512 and self.shift_count == 128 and self.input_count == 2 * self.bootstrap

    def capacity(self, kind):
        if kind == 0 and self.state == 2:
            return self.input_count < 2 * self.bootstrap
        if kind == 0 and self.state == 16:
            group = self.input_count // 256
            issue = self.next_read()
            return group == 3 and (issue is None or issue[0] != 1)
        return super().capacity(kind)

    def accept_load(self, inp, reading, bank_generation, cycle):
        if (inp.get('load') and inp['load_kind'] == 0 and (self.state == 2 or self.boot_load)
                and self.input_count // 256 in (2, 3)):
            gen = self.input_count // 256 % 2
            assert not reading or gen != bank_generation
            self.input_banks[gen], self.upper_banks[gen] = self.upper_banks[gen], self.input_banks[gen]
            self.input_owner[gen], self.upper_owner[gen] = self.upper_owner[gen], self.input_owner[gen]
            super().accept_load(inp, reading, bank_generation, cycle)
            self.input_banks[gen], self.upper_banks[gen] = self.upper_banks[gen], self.input_banks[gen]
            self.input_owner[gen], self.upper_owner[gen] = self.upper_owner[gen], self.input_owner[gen]
        else:
            super().accept_load(inp, reading, bank_generation, cycle)

    def tick(self, inp, control):
        if self.state != 16 or inp.get('reset'):
            return super().tick(inp, control)
        read = self.next_read()
        execute = self.boot_pipe[1]
        auxiliary = self.aux_pipe[1]
        if self.aux_write:
            tile, quartet, row = self.aux_write
            assert not execute or execute[0][2] != quartet ^ 2
            words = []
            for offset in range(4):
                lane = 16 * row + 4 * (quartet ^ 2) + offset
                assert self.products[lane] == 64 and self.seeds[lane] == 1
                col = 4 * quartet + offset
                words.append(((8 + row) * 256 + 16 * tile + col, q16.rne(self.acc[lane], self.shift[lane])))
                self.products[lane] = self.seeds[lane] = 0
            self.queue.store_scratch(words)
            self.aux_write = (tile, quartet, row + 1) if row < 3 else None
            if row == 3:
                self.physical_use[quartet ^ 2] = None
                self.commits += 1
        if execute:
            assert self.physical_use[execute[0][2]] is None
        if auxiliary:
            assert execute and execute[0] == auxiliary[0]
            (_, tile, quartet, k), inputs = auxiliary
            target = quartet ^ 2
            if k == 0:
                assert self.physical_use[target] is None and self.bias_shadow == tile
                self.physical_use[target] = tile, quartet
            assert self.physical_use[target] == (tile, quartet)
            for row, (identity, value) in enumerate(inputs):
                assert identity == (8 + row) * 64 + k
                for offset, weight in enumerate(execute[2]):
                    lane = row * 16 + target * 4 + offset
                    if k == 0:
                        col = 16 * tile + 4 * quartet + offset
                        assert self.products[lane] == self.seeds[lane] == 0
                        self.acc[lane] = q16.signed(self.bias[col], 36)
                        self.shift[lane] = self.shifts[col]
                        self.seeds[lane] = 1
                    assert self.products[lane] == k
                    self.acc[lane] = q16.signed(self.acc[lane] + value * weight, 36)
                    self.products[lane] += 1
            self.aux_executes += 1
            self.mac_cycles[target] += 1
        if self.boot_emit and auxiliary is None:
            group, tile, quartet = self.boot_emit
            if group == 1 and 7 <= tile <= 14:
                assert self.aux_write is None
                self.aux_write = tile, quartet, 0
        token = None
        if read and read[0] == 1:
            self.input_port_wait += int(self.bootstrap == 384 and self.input_count // 256 == 3)
            if 7 <= read[1] <= 14:
                assert self.upper_owner[0] == 2
                token = read, [self.upper_banks[0][row][read[3]] for row in range(4)]
                assert all(word is not None for word in token[1])
                self.aux_issues += 1
        self.aux_pipe = [token, self.aux_pipe[0]]
        self.boot_load = True
        popped = super().tick(inp, control)
        self.boot_load = False
        if self.state != 16:
            assert self.aux_write is None and self.physical_use == [None] * 4
            for gen, group in enumerate((2, 3)):
                assert self.input_owner[gen] is None and self.upper_owner[gen] in (None, group)
                self.input_owner[gen], self.input_banks[gen] = self.upper_owner[gen], self.upper_banks[gen]
        return popped

def save(name, value):
    (REPORT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def simulate(mode, case, program, initial, first, compare=None):
    t.staged.patch_parameter_limit(prologue=True)
    bootstrap = BOOTSTRAP[mode]
    core = trb.ReuseCore(case) if mode == 'M0' else K8Core(case, bootstrap)
    row = t.simulate('I', 'response_relative', case, adapt(program, bootstrap), initial, first, 0,
        compare=compare, make_core=lambda _: core, bootstrap=bootstrap,
        parameter_layout=trb.sg.p2.quartet_layout, make_port=partial(StartupPort, bootstrap=bootstrap),
        host_schedule=partial(startup_host, bootstrap=bootstrap), make_wrapper=ChainWrapper,
        descriptor_count=54-bootstrap//128)
    assert core.mac_cycles == [25600] * 4 and core.commits == 1600
    assert core.queue.reads == core.queue.writes == 25344
    assert len(core.boot_launch) == 128
    row.update(mode=mode, joins=core.joins, input_ready=core.input_ready_cycles,
               prologue_done=core.boot_done_cycle, output_ready=core.queue.group_ready,
               output_freed=core.queue.group_freed, reuse_wait_count=len(core.reuse_wait))
    if mode != 'M0':
        assert core.aux_issues == core.aux_executes == 2048
        assert core.queue.scratch_writes == core.queue.scratch_reads == 512
        row.update(aux_mac_cycles=core.aux_executes, scratch_writes=core.queue.scratch_writes,
                   scratch_reads=core.queue.scratch_reads, prologue_input_blocks=core.input_port_wait,
                   parameter_weight_halfwords_read=401408, input_macro_reads=107520)
    return row


def main():
    program, initial, first, rows = observe()
    args = sys.argv[1:]
    if len(args) == 1 and args[0] in ('K8-3', 'K8-4'):
        row = simulate(args[0], 0, program, initial, first)
        print(row['cold_cycles'], row['prologue_done'], flush=True)
        return
    base = simulate('M0', 0, program, initial, first, rows)
    actual = {key: base[key] for key in ANCHORS}
    save('calibration.json', dict(passed=actual == ANCHORS, actual=actual, native=ANCHORS, model=base))
    print('CALIBRATION', actual, base['differences'][:5], [d['cycle'] for d in base['descriptor_trace'][:8]], flush=True)
    if args == ['calibrate']:
        return
    assert actual == ANCHORS
    rows = [base]
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = [(mode, case, pool.submit(simulate, mode, case, program, initial, first))
                for mode in BOOTSTRAP for case in range(12) if (mode, case) != ('M0', 0)]
        for mode, case, job in jobs:
            row = job.result()
            rows.append(row)
            print(mode, case+1, row['cold_cycles'], flush=True)
    totals = {mode: sum(row['cold_cycles'] for row in rows if row['mode'] == mode) for mode in BOOTSTRAP}
    selected = min(('K8-4', 'K8-3'), key=lambda mode: totals[mode])
    if totals[selected] >= totals['M0']:
        selected = None
    save('model-results.json', dict(totals=totals, selected=selected,
         throughput={mode: 1800000000 / cycles for mode, cycles in totals.items()}, rows=rows))
    print('SELECTION', selected, totals, flush=True)

if __name__ == '__main__':
    main()



