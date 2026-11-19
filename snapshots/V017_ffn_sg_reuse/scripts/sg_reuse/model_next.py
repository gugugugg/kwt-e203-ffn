"""Use frozen S+G handshakes to drive the slot reuse experiment."""
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_sg_reuse'
TRACE = REPORT / 'received/observation/native-evidence' / REPORT.relative_to(ROOT) / 'observation/events.csv'
NATIVE = ROOT / 'reports/optimization/complete_soc/ffn_ps_SG'
MODES = ('M0', 'T', 'TR', 'TRB')
spec = importlib.util.spec_from_file_location('sg_parent_model', ROOT / 'scripts/p2_startup/model.py')
sg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg)
t, q16 = sg.t, sg.q16


def observation():
    pending, program, host, rows = {}, [], [], {}
    for row in t.m3.trace_rows(TRACE):
        cycle = row['cycle']
        rows[cycle] = row
        for bus in ('cpu', 'shared_cpu'):
            if row[bus + '_cmd_valid'] and bus not in pending:
                pending[bus] = dict(bus=bus, start=cycle, **{
                    key: row[bus + '_cmd_' + signal] for key, signal in
                    (('read', 'read'), ('address', 'addr'), ('data', 'wdata'), ('mask', 'wmask'))})
            if row[bus + '_cmd_valid'] and row[bus + '_cmd_ready']:
                pending[bus]['accept'] = cycle
            if row[bus + '_rsp_valid'] and row[bus + '_rsp_ready'] and bus in pending:
                program.append(dict(pending.pop(bus), response=cycle))
        if row['host_cmd_valid'] and row['host_cmd_ready']:
            assert not row['host_cmd_read'] and row['host_cmd_wmask'] == 15
            host.append((row['host_cmd_addr'], row['host_cmd_wdata']))
    program.sort(key=lambda command: command['start'])
    prior = 0
    for cmd in program:
        cmd['gap'] = cmd['start'] - prior
        assert cmd['gap'] > 0
        prior = cmd['response']
    assert len(host) == 11690 and host[0][0] == 0 and host[10] == (t.READY_WORD, 1)
    return program, host[1:10], 2, rows


def descriptor_program(program, chain):
    head = [dict(cmd) for cmd in program[:39]]
    descriptors = [program[i:i+4] for i in range(39, len(program), 4)]
    inputs = [d for d in descriptors if d[2]['data'] == 1]
    outputs = [d for d in descriptors if d[2]['data'] == 2]
    assert len(inputs) == 23 and len(outputs) == 25
    tail = []
    for out, incoming in zip(outputs, inputs):
        tail.extend((incoming, out))
    tail.extend(outputs[23:])
    rebuilt = []
    for i, descriptor in enumerate(tail):
        first, *rest = map(dict, descriptor)
        first['gap'] = 6 if i == 0 else 20 if descriptor[2]['data'] == 1 else 14 if i < 46 else 20
        for command in [first] + rest:
            command['start'] = program[39+len(rebuilt)]['start']
            rebuilt.append(command)
    if chain:
        head[27]['data'] = 3
        head = head[:28] + [dict(head[33], gap=7), head[34], head[36]] + head[37:]
    return head + rebuilt


class TailPort(sg.StartupPort):
    def __init__(self, wrapper, mode):
        super().__init__(wrapper, mode)
        self.tail_writes = 0

    def dual_eligible(self, stream, background, command):
        return (super().dual_eligible(stream, background, command)
                or background and command['read'] and 32768 <= t.word_address(command) < 40960)

    def tick(self, command, response_ready, cycle):
        edge = self.current
        super().tick(command, response_ready, cycle)
        if edge['dual'] and edge['background']:
            assert edge['host']['address'] == self.prefix
            self.prefix += 1
            self.last_input = cycle
            self.late_writes += 1
            self.tail_writes += 1


class ReuseQueue(sg.p2.wave.Output):
    def reset(self):
        super().reset()
        self.reuse = [None, None]
        self.wrapped_singles = 0

    @staticmethod
    def location(index):
        group, offset = divmod(index, 1024)
        row, col = divmod(offset, 256)
        if group < 2:
            return 4 * (row ^ (col // 4 % 4)) + col % 4, 64 * group + 16 * row + col // 16
        return q16.Output16.location(index)

    def available(self, group):
        gen = group % 2
        return self.groups[gen] is None or (
            group in (2, 3) and self.groups[gen] == group - 2
            and self.ready[gen] and self.reuse[gen] is None)

    def acquire(self, group):
        gen = group % 2
        if self.groups[gen] is None:
            super().acquire(group)
        else:
            assert self.available(group)
            self.reuse[gen] = group

    def write(self, group, words):
        if group not in (2, 3):
            return super().write(group, words)
        gen = group % 2
        assert self.reuse[gen] == group or self.groups[gen] == group and not self.ready[gen]
        touched = set()
        for index, value in words:
            bank, addr = self.location(index)
            previous = self.banks[bank][addr]
            assert bank not in touched and index // 1024 == group
            assert previous is None or previous[0] // 1024 == group - 2 and previous[0] < self.retired
            self.banks[bank][addr] = index, value
            touched.add(bank)
            self.writes += 1

    def comb(self, item, single, pair, commit_rows=0):
        pop, index, count, blocked, rows = super().comb(item, single, pair, commit_rows)
        if index < 2048 and index % 4 == 3 and count == 2:
            count = 1
        return pop, index, count, blocked, rows

    def tick(self, control, cycle):
        _, index, count, _, _ = control
        self.wrapped_singles += int(index < 2048 and index % 4 == 3 and count == 1)
        popped = super().tick(control, cycle)
        for gen, group in enumerate(self.reuse):
            if group is not None and self.groups[gen] is None:
                self.groups[gen], self.reuse[gen] = group, None
        return popped


class ReuseCore(sg.Core):
    def __init__(self, case):
        super().__init__(case, True)
        self.queue = ReuseQueue()
        self.queue.reset()

    def reset(self):
        super().reset()
        self.requests = [None] * 5
        self.cursor = None
        self.reuse_wait = []

    def wave_emission(self):
        for quartet, token in enumerate(self.requests[1:]):
            if token and token[1]:
                return token[1] + (quartet,)
        return None

    def tick(self, inp, control):
        if inp.get('reset'):
            self.reset()
            return []
        if self.state != 7:
            group = self.row // 4
            if self.state == 15 and self.complete() and self.queue.available(group):
                self.queue.acquire(group)
                popped = self.queue.tick(control['out'], self.cycle)
                self.accept_load(inp, False, group % 2, self.cycle)
                self.state = 3
                return self.retire(popped)
            previous = self.state
            # Skip S+G's wall-clock phase tracking. The pipe below carries
            # explicit requests and bubbles through the four column groups.
            popped = sg.p2.Core.tick(self, inp, control)
            if previous == 6 and self.state == 7:
                self.wave_base = self.wave_last = group
                self.requests = [((group, 0, 0), None), None, None, None, None]
                self.input_pipe = [None] * 4
                self.cursor = (group, 0, 1)
            return popped

        request, reserve = self.request()
        emit = self.wave_emission()
        popped = self.queue.tick(control['out'], self.cycle)
        if reserve is not None:
            self.queue.acquire(reserve)
            self.wave_last = reserve
        lead = self.requests[1]
        if lead and lead[0]:
            self.prefetch_bias(*lead[0])
        if emit:
            self.quantize(*emit)
        for quartet, token in enumerate(self.requests[1:]):
            if token and token[0]:
                self.mac(quartet, token[0])

        self.input_pipe = [self.input_q] + self.input_pipe[:3]
        self.requests = [request] + self.requests[:4]
        self.input_q = None
        bank = self.row // 4 % 2
        reading = request is not None and request[0] is not None
        if reading:
            group, _, k = request[0]
            bank = group % 2
            assert self.input_owner[bank] == group
            self.input_q = [self.input_banks[bank][r][k] for r in range(min(4, 99 - 4 * group))]
            assert all(word is not None for word in self.input_q)
        self.accept_load(inp, reading, bank, self.cycle)
        self.inner += 1
        if emit and emit[1:] == (15, 3):
            group = emit[0]
            self.input_owner[group % 2] = None
            self.queue.complete(group, self.cycle)
            if self.wave_last > group:
                self.row = 4 * (group + 1)
            else:
                self.state = 14
        return self.retire(popped)

    def request(self):
        if self.cursor is None:
            return None, None
        group, tile, k = self.cursor
        emit = None
        if k == 64:
            emit = group, tile
        elif k == 0:
            emit = (group, tile - 1) if tile else (group - 1, 15)
        if emit and emit[0] in (2, 3):
            limit = 1024 * (emit[0] - 2) + 64 * (emit[1] + 1)
            if self.queue.retired < limit:
                self.reuse_wait.append((self.cycle, emit[0], emit[1], self.queue.retired, limit))
                return None, None

        reserve = None
        if k == 64:
            self.cursor = None
            return (None, emit), None
        if k < 63:
            self.cursor = group, tile, k + 1
        elif tile < 15:
            self.cursor = group, tile + 1, 0
        else:
            successor = group + 1
            loaded = self.input_count >= min(99, 4 * (successor + 1)) * 64
            available = self.queue.available(successor)
            joined = group < 24 and loaded and available
            if group < 24:
                self.joins.append(dict(cycle=self.cycle, group=successor, input_committed=loaded,
                                       output_empty=self.queue.groups[successor % 2] is None, joined=joined))
            if joined:
                reserve = successor
                self.cursor = successor, 0, 0
            else:
                self.cursor = group, tile, 64
        return ((group, tile, k), emit), reserve

    def prefetch_bias(self, group, tile, k):
        target = (tile + 1) % 16
        if group == 24 and tile == 15:
            return
        if 56 <= k <= 63:
            pair = k - 56
            assert self.bias_return == (target, pair)
            col = 16 * target + 2 * pair
            self.shadow[pair] = target, tuple(zip(self.bias[col:col+2], self.shifts[col:col+2]))
        if 55 <= k <= 62:
            self.bias_return = target, k - 55

    def quantize(self, group, tile, quartet):
        words = []
        for row in range(min(4, 99 - 4 * group)):
            for col in range(4 * quartet, 4 * quartet + 4):
                lane = 16 * row + col
                assert self.products[lane] == 64 and self.seeds[lane] == 1
                value = q16.rne(self.acc[lane], self.shift[lane])
                words.append(((4 * group + row) * 256 + 16 * tile + col, value))
                self.products[lane] = self.seeds[lane] = 0
                if tile < 15 or 4 * (group + 1) + row < 99:
                    target, pair = self.shadow[col // 2]
                    assert target == (tile + 1) % 16
                    bias, shift = pair[col % 2]
                    self.acc[lane], self.shift[lane] = q16.signed(bias, 36), shift
                    self.seeds[lane] = 1
        self.queue.write(group, words)
        self.commits += 1

    def mac(self, quartet, token):
        group, tile, k = token
        inputs = self.input_pipe[quartet]
        assert inputs is not None
        self.mac_cycles[quartet] += 1
        for row, (identity, value) in enumerate(inputs):
            assert identity == (4 * group + row) * 64 + k
            for col in range(4 * quartet, 4 * quartet + 4):
                lane = 16 * row + col
                assert self.seeds[lane] == 1 and self.products[lane] == k
                weight = self.weights[256 * k + 16 * tile + col]
                self.acc[lane] = q16.signed(self.acc[lane] + value * weight, 36)
                self.products[lane] += 1


class ChainWrapper(q16.q8.Wrapper64):
    steps = ((0x18, 1), (8, 1), (12, 0), (0x48, 1))

    def __init__(self, case):
        super().__init__(case, True)
        self.chain = None
        self.programmed = set()
        self.next_internal = 0

    def comb(self, cpu):
        command = cpu
        internal = self.chain in range(len(self.steps))
        if internal:
            command = t.m3.sr.idle_cpu()
            command['address'], command['data'] = self.steps[self.chain]
            command.update(valid=int(self.core.cycle >= self.next_internal), read=0, mask=15)
        elif self.chain == 'input' and cpu['valid'] and cpu['read'] and cpu['address'] == 0x50:
            command = dict(cpu, valid=0)
        elif cpu['valid'] and not cpu['read'] and cpu['address'] == 0x48 and cpu['data'] == 3:
            command = dict(cpu, data=1)
        c = super().comb(command)
        c['chain_cpu'] = command
        c['internal'] = internal
        if internal or command is not cpu and not command['valid']:
            c['internal_done'] = bool(command['valid'] and c['cpu_ready'] and (
                c['cpu_valid'] or self.chain == 3))
            c['cpu_ready'] = c['cpu_valid'] = False
        return c

    def tick(self, cpu, c, cycle):
        command = c['chain_cpu']
        if c['launch'] and cpu['data'] == 3 and not c['internal']:
            self.chain = 'input'
            self.programmed.clear()
        elif self.chain == 'input' and c['csr_fire'] and not command['read']:
            self.programmed.add(command['address'])
        if c.get('internal_done'):
            self.chain += 1
            self.next_internal = cycle + 2
            if self.chain == len(self.steps):
                self.chain = None
        can_start = (self.chain == 'input' and self.programmed == {0x40, 0x44}
                     and not self.engine.pd_active and not self.csr_rsp_valid and self.core.layer_ready())
        popped = super().tick(command, c, cycle)
        if can_start:
            self.chain = 0
            self.next_internal = cycle + 1
        return popped 


def simulate(mode, pace, case, program, initial, first, compare=None):
    t.staged.patch_parameter_limit(prologue=True)
    core = sg.Core(case, True) if mode == 'M0' else ReuseCore(case)
    selected = program if mode == 'M0' else descriptor_program(program, mode == 'TRB')
    row = t.simulate('I', pace, case, selected, initial, first, 0, compare=compare,
        make_core=lambda _: core, bootstrap=256, parameter_layout=sg.p2.quartet_layout,
        make_port=TailPort if mode in ('TR', 'TRB') else sg.StartupPort,
        host_schedule=sg.startup_host, make_wrapper=ChainWrapper if mode == 'TRB' else None)
    assert core.mac_cycles == [25600] * 4 and core.commits == 1600
    assert len(core.boot_launch) == 128
    row.update(mode=mode, joins=core.joins, input_ready=core.input_ready_cycles,
        output_generation_ready=core.queue.group_ready, output_generation_freed=core.queue.group_freed,
        reuse_wait=getattr(core, 'reuse_wait', []),
        transposed_boundary_singles=getattr(core.queue, 'wrapped_singles', 0))
    return row


def anchors(case):
    import re
    log = (NATIVE / ('run_%02d.log' % (2 * case - 1))).read_text()
    lines = [line for line in log.splitlines() if line.startswith(
        ('FFN_TRANSPORT_PHASE ', 'LOADING_DMA_COUNTS ', 'UNIFIED_PUBLIC_TASK_PASS '))]
    fields = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', '\n'.join(lines))}
    return {dest: fields[key] for dest, key in (
        ('first_mac', 'mac_first'), ('last_emit', 'last_emit'), ('final_physical_commit', 'last_commit'),
        ('final_ack', 'last_ack'), ('cold_cycles', 'cycles'))}


def save(name, value):
    (REPORT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def batch(mode, pace, start, program, initial, first):
    return [simulate(mode, pace, case, program, initial, first) for case in range(start, start+3)]


def main():
    program, initial, first, native = observation()
    reference = simulate('M0', 'response_relative', 0, program, initial, first, compare=native)
    actual = anchors(1)
    measured = {key: reference[key] for key in actual}
    save('model-calibration.json', dict(native=actual, model=measured, differences=reference['differences']))
    print('calibration', actual, measured, reference['differences'], flush=True)
    assert actual == measured and not reference['differences']
    if '--calibrate' in sys.argv:
        return
    if len(sys.argv) == 2 and sys.argv[1] in MODES:
        mode = sys.argv[1]
        row = simulate(mode, 'response_relative', 0, program, initial, first)
        save('trial-' + mode + '.json', row)
        print(mode, row['cold_cycles'], flush=True)
        return
    totals = {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for pace in t.PACINGS:
            totals[pace] = {}
            for mode in MODES:
                jobs = [pool.submit(batch, mode, pace, start, program, initial, first)
                        for start in range(0, 12, 3)]
                rows = [row for job in jobs for row in job.result()]
                if mode == 'M0':
                    for row in rows:
                        native_anchors = anchors(row['case'])
                        assert {key: row[key] for key in native_anchors} == native_anchors
                total = totals[pace][mode] = sum(row['cold_cycles'] for row in rows)
                save('model-%s-%s.json' % (mode, pace), rows)
                print(pace, mode, total, flush=True)
    relative = totals['response_relative']
    order = sorted((mode for mode in MODES[1:] if relative[mode] < 400000),
                   key=lambda mode: (relative[mode], MODES.index(mode)))
    save('model-selection.json', dict(totals=totals, eligible=order, winner=order[0] if order else None,
                                      clock_hz=150000000, exclusive_total_limit=400000))


if __name__ == '__main__':
    main()
