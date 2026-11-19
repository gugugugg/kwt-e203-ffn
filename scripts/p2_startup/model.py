"""Calibrate frozen P2 and compare startup and group-boundary schedules."""
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_p2_startup'
TRACE = (REPORT / 'received/observation/native-evidence'
         / REPORT.relative_to(ROOT) / 'observation/events.csv')
NATIVE = ROOT / 'reports/optimization/complete_soc/ffn_wp_P2'
MODES = ('M0', 'S', 'G', 'SG')
sys.path.insert(0, str(ROOT / 'scripts/taskflow_study'))
spec = importlib.util.spec_from_file_location('p2_prologue_model', ROOT / 'scripts/w4z_prologue/screen.py')
p2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p2)

t, q16 = p2.t, p2.q16


class StartupPort(p2.Port):
    def committed(self, word):
        if p2.BIAS_WORD <= word < t.PARAMETER_END:
            return self.biases == 256
        return super().committed(word)

    def stream_address(self, word):
        return (super().stream_address(word)
                or word == p2.BIAS_WORD + self.biases and self.biases < 256
                or word == t.SHIFT_WORD + self.shift_prefix and self.shift_prefix < 64
                or word == self.prefix and self.prefix < 256)

    def dual_read(self, command):
        return (super().dual_read(command)
                or t.m3.input_read(command) and 0 <= t.word_address(command) < 256)

    def commit_host(self, addr, data, cycle):
        if addr == t.READY_WORD and data == 1:
            self.stream_start = cycle
        else:
            super().commit_host(addr, data, cycle)

    def tick(self, command, response_ready, cycle):
        edge = self.current
        super().tick(command, response_ready, cycle)
        if edge['dual'] and edge['host']['address'] < 256:
            assert edge['host']['address'] == self.prefix
            self.prefix += 1
            self.last_input = cycle


def startup_host(early, loaded, late, image):
    bias, shift, mailbox, weights = loaded[:256], loaded[256:320], loaded[320], loaded[321:]
    assert mailbox == (t.READY_WORD, 1)
    words = early[:1] + early[256:] + [mailbox] + shift + bias + early[1:256] + weights + late
    return words, len(words)


class Core(p2.Core):
    def __init__(self, case, join):
        self.join_enabled = join
        super().__init__(case, 2)

    def reset(self):
        super().reset()
        self.joins = []
        self.wave_base = self.wave_last = 0

    def wave_phase(self, offset):
        if offset < 0:
            return None
        group_offset, within = divmod(offset, 1024)
        group = self.wave_base + group_offset
        if group <= self.wave_last:
            tile, k = divmod(within, 64)
            return group, tile, k
        return None

    def wave_emission(self):
        for quartet in range(4):
            token = self.wave_phase(self.age - 64 - quartet)
            if token and token[2] == 0:
                return token[0], token[1], quartet
        return None

    def comb(self, inp):
        if not self.join_enabled or self.state != 7:
            return super().comb(inp)
        emit = self.wave_emission()
        rows = min(4, 99 - 4 * emit[0]) if emit else 0
        return dict(out=self.queue.comb(self.item, inp.get('out_ready'), inp.get('out_pair_ready'), rows),
                    quant=bool(rows))

    def tick(self, inp, control):
        if not self.join_enabled or self.state != 7 or inp.get('reset'):
            previous = self.state
            popped = super().tick(inp, control)
            if self.join_enabled and previous == 6 and self.state == 7:
                self.wave_base = self.wave_last = self.row // 4
                self.weight_q[0] = (self.wave_base,) + self.weight_q[0]
            return popped

        leading = self.wave_phase(self.age)
        if leading:
            group, tile, k = leading
            target = (tile + 1) % 16
            if group < 24 or tile < 15:
                if 56 <= k <= 63:
                    pair = k - 56
                    assert self.bias_return == (target, pair)
                    col = 16 * target + 2 * pair
                    self.shadow[pair] = target, tuple(zip(self.bias[col:col+2], self.shifts[col:col+2]))
                if 55 <= k <= 62:
                    self.bias_return = target, k - 55

        # A reservation may use only the state before this cycle's queue pop or load.
        request = self.wave_phase(self.age + 2)
        reserve = None
        if request and request[1:] == (15, 63) and request[0] < 24:
            next_group = request[0] + 1
            loaded = self.input_count >= min(99, 4 * (next_group + 1)) * 64
            empty = self.queue.groups[next_group % 2] is None
            self.joins.append(dict(cycle=self.cycle, group=next_group, input_committed=loaded,
                                   output_empty=empty, joined=loaded and empty))
            if loaded and empty:
                reserve = next_group

        popped = self.queue.tick(control['out'], self.cycle)
        if reserve is not None:
            self.queue.acquire(reserve)
            self.wave_last = reserve

        emit = self.wave_emission()
        if emit:
            group, tile, quartet = emit
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

        for quartet in range(4):
            token = self.wave_phase(self.age - quartet)
            assert self.weight_pipe[quartet] == token
            if token is None:
                continue
            group, tile, k = token
            inputs = self.input_pipe[quartet]
            assert inputs is not None
            if not k and (tile or group > self.wave_base):
                assert emit == ((group if tile else group - 1), (tile - 1) % 16, quartet)
                self.fused += 1
            self.mac_cycles[quartet] += 1
            for row, (identity, value) in enumerate(inputs):
                assert identity == (4 * group + row) * 64 + k
                for col in range(4 * quartet, 4 * quartet + 4):
                    lane = 16 * row + col
                    assert self.seeds[lane] == 1 and self.products[lane] == k
                    weight = self.weights[256 * k + 16 * tile + col]
                    self.acc[lane] = q16.signed(self.acc[lane] + value * weight, 36)
                    self.products[lane] += 1

        self.input_pipe = [self.input_q] + self.input_pipe[:3]
        self.weight_pipe = self.weight_q
        self.weight_q = [self.wave_phase(self.age + 2 - q) for q in range(4)]
        assert request == self.weight_q[0]
        self.input_q = None
        bank = self.row // 4 % 2
        if request:
            group, _, k = request
            bank = group % 2
            assert self.input_owner[bank] == group
            self.input_q = [self.input_banks[bank][r][k] for r in range(min(4, 99 - 4 * group))]
            assert all(word is not None for word in self.input_q)
        self.accept_load(inp, request is not None, bank, self.cycle)
        self.age += 1
        self.inner = self.age
        if emit and emit[1:] == (15, 3):
            group = emit[0]
            self.input_owner[group % 2] = None
            self.queue.complete(group, self.cycle)
            if self.wave_last > group:
                self.row = 4 * (group + 1)
            else:
                self.state = 14
        return self.retire(popped)


def observation():
    pending, program, host, rows = {}, [], [], {}
    for row in t.m3.trace_rows(TRACE):
        cycle = row['cycle']
        rows[cycle] = row
        for bus in ('cpu', 'shared_cpu'):
            if row[bus + '_cmd_valid'] and bus not in pending:
                pending[bus] = dict(bus=bus, start=cycle, **{
                    key: row[bus + '_cmd_' + signal] for key, signal in
                    (('read','read'), ('address','addr'), ('data','wdata'), ('mask','wmask'))})
            if row[bus + '_cmd_valid'] and row[bus + '_cmd_ready']:
                pending[bus]['accept'] = cycle
            if row[bus + '_rsp_valid'] and row[bus + '_rsp_ready'] and bus in pending:
                program.append(dict(pending.pop(bus), response=cycle))
        if row['host_cmd_valid'] and row['host_cmd_ready']:
            assert not row['host_cmd_read'] and row['host_cmd_wmask'] == 15
            host.append((cycle, row['host_cmd_addr'], row['host_cmd_wdata']))
    program.sort(key=lambda command: command['start'])
    prior = 0
    for cmd in program:
        cmd['gap'] = cmd['start'] - prior
        assert cmd['gap'] > 0
        prior = cmd['response']
    assert [addr for _, addr, _ in host[:256]] == list(range(256))
    initial = [(addr, data) for _, addr, data in host[256:265]]
    bias_cycle, bias_addr, _ = host[265]
    request = next(cmd['accept'] for cmd in program if cmd['address'] == t.PARAMETER_REQUEST)
    assert len(host) == 11690 and bias_addr == p2.BIAS_WORD
    return program, initial, host[0][0], bias_cycle - request, rows


def startup_program(program):
    assert [c['data'] for c in program[11:23] if c['address'] == 8] == [1, 5]
    assert [c['data'] for c in program[11:23] if c['address'] == 0x40] == [0xa0028000, 0xa003a000]
    steps = [dict(c) for c in program[:11] + program[17:23] + program[11:17] + program[23:]]
    steps[11]['gap'] = program[11]['gap']  # return from firmware's mailbox handshake
    steps[17]['gap'] = program[23]['gap']  # inter-descriptor transition
    steps[23]['gap'] = program[17]['gap']
    for i in range(11, 23):
        steps[i]['start'] = program[i]['start']
    return steps


def anchors(case):
    log = (NATIVE / ('run_%02d.log' % (2 * case - 1))).read_text()
    lines = [line for line in log.splitlines() if line.startswith(
        ('FFN_TRANSPORT_PHASE ', 'LOADING_DMA_COUNTS ', 'UNIFIED_PUBLIC_TASK_PASS '))]
    fields = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', '\n'.join(lines))}
    return {dest: fields[key] for dest, key in (
        ('first_mac', 'mac_first'), ('last_emit', 'last_emit'), ('final_physical_commit', 'last_commit'),
        ('final_ack', 'last_ack'), ('cold_cycles', 'cycles'))}


def evaluate(mode, pace, case, program, initial, first, gap, compare=None):
    t.staged.patch_parameter_limit(prologue=True)
    startup = mode in ('S', 'SG')
    core = Core(case, mode in ('G', 'SG'))
    row = t.simulate('I', pace, case, startup_program(program) if startup else program,
                     initial, first, gap, compare=compare, make_core=lambda _: core,
                     bootstrap=256, parameter_layout=p2.quartet_layout,
                     make_port=StartupPort if startup else p2.Port,
                     host_schedule=startup_host if startup else None)
    assert core.mac_cycles == [25600] * 4 and core.commits == 1600
    assert len(core.boot_launch) == 128
    row.update(mode=mode, joins=core.joins, joined_groups=sum(j['joined'] for j in core.joins),
               boot_done_cycle=core.boot_done_cycle, output_generation_ready=core.queue.group_ready,
               output_generation_freed=core.queue.group_freed, input_ready=core.input_ready_cycles)
    return row


def batch(mode, pace, start, program, initial, first, gap):
    return [evaluate(mode, pace, case, program, initial, first, gap)
            for case in range(start, start + 3)]


def save(name, data):
    (REPORT / name).write_text(json.dumps(data, indent=2) + '\n')


def main():
    program, initial, first, gap, native = observation()
    m0 = evaluate('M0', 'response_relative', 0, program, initial, first, gap, compare=native)
    actual = anchors(1)
    previous, old_initial, old_first, old_gap, _ = t.load_observation()
    old_program = p2.prologue_program(previous, 2)
    old = evaluate('M0', 'response_relative', 0, old_program, old_initial, old_first, old_gap)
    checks = {key: m0[key] for key in actual}
    passed = checks == actual and not m0['differences']
    save('model-calibration.json', dict(passed=passed, native=actual, model=checks,
        previous_model={key: old[key] for key in actual}, differences=m0['differences'],
        native_host_first=first, native_bias_after_layer_request=gap, prior_host_first=old_first,
        prior_bias_after_layer_request=old_gap, old_descriptors=old['descriptor_trace'],
        calibrated_descriptors=m0['descriptor_trace']))
    print('calibration', passed, checks, m0['differences'], flush=True)
    if not passed:
        raise SystemExit('M0 disagrees with frozen native observation')
    if '--calibrate' in sys.argv:
        return
    totals = {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for pace in t.PACINGS:
            totals[pace] = {}
            for mode in MODES:
                jobs = [pool.submit(batch, mode, pace, start, program, initial, first, gap)
                        for start in range(0, 12, 3)]
                rows = [row for job in jobs for row in job.result()]
                if mode == 'M0':
                    for row in rows:
                        actual = anchors(row['case'])
                        assert {key: row[key] for key in actual} == actual, (pace, row['case'])
                total = totals[pace][mode] = sum(row['cold_cycles'] for row in rows)
                save('model-%s-%s.json' % (mode, pace), rows)
                print(pace, mode, total, rows[0]['joined_groups'], flush=True)
    relative = totals['response_relative']
    order = sorted((mode for mode in MODES[1:] if relative[mode] < 414432),
                   key=lambda mode: (relative[mode], MODES.index(mode)))
    save('model-selection.json', dict(totals=totals, order=order,
        winner=order[0] if order else None, clock_hz=150000000, stretch_total=404494))


if __name__ == '__main__':
    main()
