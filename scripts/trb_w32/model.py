"""Causal W32 screen on the frozen T+R+B transactions and physical ports."""
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_trb_w32'
spec = importlib.util.spec_from_file_location('k8_transport', ROOT / 'scripts/trb_k8/model.py')
frozen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frozen)
trb, t, q16 = frozen.trb, frozen.t, frozen.q16
S = q16.signed
SHIFTS = (0, 13, 14, 15, 16, 17, 18)


class PairCore(trb.ReuseCore):
    def reset(self):
        super().reset()
        self.bias_low = [None] * 256
        self.shift_packed = [None] * 256
        self.correction = None
        self.a_even, self.a_sum, self.a_seen = {}, {}, {}
        self.w_even, self.w_sum, self.w_seen = {}, {}, {}
        self.a_ready, self.w_ready = set(), set()
        self.raw_requested = self.raw_captured = 0
        self.raw_cache = {}
        self.bias_pending = None
        self.corrected_pairs = 0
        self.boot_cache = {}
        self.next_seed_pair = 0
        self.even_inputs = [None] * 4
        self.multiply = [None] * 4
        self.second = [None] * 4
        self.emit_pipe = [None, None]
        self.lane_tag = [None] * 64
        self.first_source = None
        self.first_bias = None
        self.peak_raw = self.peak_boot_cache = 0
        self.bias_reads_count = dict(raw=0, seed=0, steady=0, initial=0)
        self.correction_counts = dict(input=0, weight=0)
        self.bias_writes_count = 0
        self.seed_wait = 0

    @property
    def boot_mac(self):
        return self.state == 16 and any(self.multiply)

    def layer_ready(self):
        return super().layer_ready() and {0, 1} <= self.a_ready

    def complete(self):
        return super().complete() and self.row // 4 in self.a_ready

    def next_read(self):
        if self.state != 16 or self.reserve < 2:
            return None
        batch, offset = divmod(self.boot_position, 128)
        if batch == 64 or self.weight_count < (batch + 1) * 256:
            return None
        tile, quartet = divmod(batch, 4)
        group, k = divmod(offset, 64)
        if len(self.boot_cache.get(batch, ())) != 4:
            return None
        return group, tile, quartet, k

    def request(self):
        # A new generation cannot be reserved before its final correction retires.
        old = self.input_count
        if self.cursor and self.cursor[1:] == (15, 63):
            successor = self.cursor[0] + 1
            if successor not in self.a_ready:
                self.input_count = min(old, successor * 256)
        try:
            return super().request()
        finally:
            self.input_count = old

    def read_bias(self, pair):
        col = 2 * pair
        data = tuple((self.bias_low[i], self.shift_packed[i]) for i in (col, col + 1))
        assert all(low is not None and packed is not None for low, packed in data)
        return data

    @staticmethod
    def decode(data):
        return [(S(low | ((packed >> 3) << 32), 36), SHIFTS[packed & 7])
                for low, packed in data]

    def prologue_bias(self):
        pending = self.bias_pending
        self.bias_pending = None
        pair = self.corrected_pairs
        batch = pair // 2
        if batch in self.w_ready and pair in self.raw_cache:
            col = 2 * pair
            raw = self.raw_cache.pop(pair)
            for i, (low, packed) in enumerate(raw, col):
                corrected = S(S(low, 32) - self.w_sum[i], 36)
                self.bias_low[i] = corrected & 0xffffffff
                self.shift_packed[i] = ((corrected >> 32 & 15) << 3) | packed
            self.corrected_pairs += 1
            self.bias_writes_count += 1
        else:
            pair = self.next_seed_pair
            batch = pair // 2
            if pair < self.corrected_pairs and (batch in self.boot_cache or len(self.boot_cache) < 2):
                self.boot_cache.setdefault(batch, [])
                self.bias_pending = 'seed', pair, self.read_bias(pair)
                self.next_seed_pair += 1
                self.bias_reads_count['seed'] += 1
            elif self.raw_requested < min(128, 2 * ((self.weight_count + 255) // 256)):
                pair = self.raw_requested
                self.bias_pending = 'raw', pair, self.read_bias(pair)
                self.raw_requested += 1
                self.bias_reads_count['raw'] += 1
        if pending:
            kind, pair, data = pending
            if kind == 'raw':
                self.raw_cache[pair] = data
                self.raw_captured += 1
            else:
                self.boot_cache[pair // 2].extend(self.decode(data))
        self.peak_raw = max(self.peak_raw, len(self.raw_cache))
        self.peak_boot_cache = max(self.peak_boot_cache, len(self.boot_cache))

    def accepted(self, inp, old_state):
        jobs = []
        if not inp.get('load'):
            return jobs
        kind = inp['load_kind']
        start = inp['load_address']
        halves = 2 if inp['load_pair'] and kind != 5 else 1
        word = inp['input_word'] if kind == 0 else inp['load_word']
        for offset in range(halves):
            addr = start + offset
            raw = word >> (16 * offset) & 65535
            value = S(raw, 16)
            if kind == 5:
                for byte in range(2):
                    shift = raw >> (8 * byte) & 255
                    self.shift_packed[2*addr+byte] = shift - 12 if 13 <= shift <= 18 else 0
            elif kind == 1 and old_state == 2:
                col, half = divmod(addr - 16384, 2)
                if not half:
                    self.bias_low[col] = raw
                else:
                    self.bias_low[col] |= raw << 16
                    assert S(self.bias_low[col], 32) == self.bias[col]
            elif kind == 1:
                tile, slot = divmod(addr, 1024)
                quartet, slot = divmod(slot, 256)
                k, col = divmod(slot, 4)
                identity = 16 * tile + 4 * quartet + col
                if k % 2 == 0:
                    self.w_even[identity] = k, value
                else:
                    even_k, even = self.w_even.pop(identity)
                    assert even_k + 1 == k
                    jobs.append((kind, identity, k, even * value))
            else:
                group, local = divmod(addr, 256)
                k, row = divmod(local, 4 if group < 24 else 3)
                identity = 4 * group + row
                if k % 2 == 0:
                    self.a_even[identity] = k, value
                else:
                    even_k, even = self.a_even.pop(identity)
                    assert even_k + 1 == k
                    jobs.append((kind, identity, k, even * value))
        assert len(jobs) <= 2
        return jobs

    def advance_correction(self, jobs):
        for kind, i, k, value in self.correction or ():
            sums, counts = (self.w_sum, self.w_seen) if kind == 1 else (self.a_sum, self.a_seen)
            assert counts.get(i, 0) == k // 2
            counts[i] = k // 2 + 1
            sums[i] = S(sums.get(i, 0) + value, 36)
            self.correction_counts['weight' if kind else 'input'] += 1
            if k == 63:
                group = i // 4
                if all(counts.get(j) == 32 for j in range(4 * group,
                        min(99, 4 * group + 4) if kind == 0 else 4 * group + 4)):
                    (self.w_ready if kind == 1 else self.a_ready).add(group)
        self.correction = jobs

    def consume_operand(self, quartet, token, inputs, weights, boot):
        group, tile, k = token
        assert all(index == (4 * group + row) * 64 + k for row, (index, _) in enumerate(inputs))
        self.mac_cycles[quartet] += 1
        if self.first_source is None:
            self.first_source = self.cycle
        if not k % 2:
            assert self.even_inputs[quartet] is None
            self.even_inputs[quartet] = token, inputs, weights
            return None
        earlier, even, old_weights = self.even_inputs[quartet]
        assert earlier == (group, tile, k-1)
        self.even_inputs[quartet] = None
        seed = None
        if k == 1:
            assert group in self.a_ready
            if boot:
                seed = self.boot_cache[4 * tile + quartet]
            else:
                seed = []
                for pair in (2 * quartet, 2 * quartet + 1):
                    target, values = self.shadow[pair]
                    assert tile == target
                    seed.extend(values)
        def arguments(lo, hi):
            args = []
            for row in range(lo, min(hi, len(inputs))):
                for col in range(4):
                    a = even[row][1] + weights[col]
                    b = inputs[row][1] + old_weights[col]
                    assert S(a, 17) == a and S(b, 17) == b
                    args.append((row, col, a, b))
            return args
        return (group, tile, k//2, seed, arguments(0,2), arguments(2,4))

    def arithmetic(self, tokens):
        for q, token in enumerate(tokens):
            job = self.multiply[q]
            if job:
                group, tile, p, seed, args = job
                for row, col, a, b in args:
                    lane = 16 * row + 4 * q + col
                    product = a * b
                    assert S(product, 34) == product
                    if p == 0:
                        assert self.lane_tag[lane] is None
                        bias, shift = seed[col]
                        self.acc[lane] = S(bias - self.a_sum[4*group+row] + product, 36)
                        self.shift[lane] = shift
                        self.lane_tag[lane] = (group, tile)
                    else:
                        assert self.lane_tag[lane] == (group, tile)
                        self.acc[lane] = S(self.acc[lane] + product, 36)
                    assert self.products[lane] == p
                    self.products[lane] += 1
            late = self.second[q]
            even_odd = self.consume_operand(q, *token) if token else None
            assert not (even_odd and late)
            self.multiply[q] = late or (even_odd[:4]+(even_odd[4],) if even_odd else None)
            self.second[q] = even_odd[:4]+(even_odd[5],) if even_odd else None

    def quantize(self, group, tile, quartet):
        words = []
        for row in range(min(4, 99 - 4 * group)):
            for col in range(4 * quartet, 4 * quartet + 4):
                lane = 16 * row + col
                assert self.products[lane] == 32 and self.lane_tag[lane] == (group, tile)
                value = q16.rne(self.acc[lane], self.shift[lane])
                words.append(((4*group+row)*256+16*tile+col, value))
                self.products[lane] = 0
                self.lane_tag[lane] = None
        self.queue.write(group, words)
        self.commits += 1

    def comb(self, inp):
        emit = self.emit_pipe[1]
        rows = min(4, 99 - 4 * emit[0]) if emit else 0
        return dict(out=self.queue.comb(self.item, inp.get('out_ready'), inp.get('out_pair_ready'), rows),
                    quant=bool(rows))

    def prefetch_bias(self, group, tile, k):
        target = (tile + 1) % 16
        if group == 24 and tile == 15:
            return
        if 56 <= k <= 63:
            pair = k - 56
            assert self.bias_return[:2] == (target, pair)
            self.shadow[pair] = target, self.decode(self.bias_return[2])
        if 55 <= k <= 62:
            pair = k - 55
            self.bias_return = target, pair, self.read_bias(8*target+pair)
            self.bias_reads_count['steady'] += 1

    def boot(self, inp, control):
        read = self.next_read()
        cycle = self.cycle
        popped = self.queue.tick(control['out'], cycle)
        if self.reserve < 2:
            self.queue.acquire(self.reserve)
            self.reserve += 1
        batch, offset = divmod(self.boot_position, 128)
        if batch < 64 and self.weight_count >= (batch+1)*256 and not read:
            self.seed_wait += 1
        emit = self.emit_pipe[1]
        if emit:
            self.quantize(*emit)
        execute = self.boot_pipe[1]
        tokens = [None] * 4
        if execute:
            (group,tile,q,k), inputs, weights = execute
            tokens[q] = (group,tile,k),inputs,weights,True
        self.arithmetic(tokens)
        self.emit_pipe = [self.boot_emit, self.emit_pipe[0]]
        self.boot_emit = (group,tile,q) if execute and k==63 else None
        token = None
        if read:
            group,tile,q,k = read
            assert self.input_owner[group] == group and group in self.a_ready
            inputs = [self.input_banks[group][row][k] for row in range(4)]
            addr = ((k ^ (k >> 1)) << 4) | tile
            weights = [self.priv_weights[col][addr] for col in range(4*q,4*q+4)]
            assert all(v is not None for v in inputs+weights)
            token = read, inputs, weights
            if k == 0:
                self.boot_launch.append((cycle,group,tile,q))
            if k == 63 and group == 1:
                del self.boot_cache[batch]
            self.boot_position += 1
        self.boot_pipe = [token,self.boot_pipe[0]]
        self.prologue_bias()
        self.load(inp, read)
        if emit and emit[1:] == (15,3):
            group = emit[0]
            self.input_owner[group] = None
            self.queue.complete(group,cycle)
            if group == 1:
                assert self.corrected_pairs == self.raw_captured == 128
                self.boot_done_cycle = cycle
                self.row, self.state = 8, 15
        return self.retire(popped)

    def wave(self, inp, control):
        request, reserve = self.request()
        emit = self.emit_pipe[1]
        popped = self.queue.tick(control['out'], self.cycle)
        if reserve is not None:
            self.queue.acquire(reserve)
            self.wave_last = reserve
        lead = self.requests[1]
        if lead and lead[0]:
            self.prefetch_bias(*lead[0])
        if emit:
            self.quantize(*emit)
        tokens = [None] * 4
        for quartet, token in enumerate(self.requests[1:]):
            if token and token[0]:
                group,tile,k = token[0]
                addr = ((k ^ (k >> 1)) << 4) | tile
                weights = [self.priv_weights[col][addr] for col in range(4*quartet,4*quartet+4)]
                tokens[quartet] = (group,tile,k),self.input_pipe[quartet],weights,False
        self.arithmetic(tokens)
        self.emit_pipe = [self.wave_emission(),self.emit_pipe[0]]
        self.input_pipe = [self.input_q]+self.input_pipe[:3]
        self.requests = [request]+self.requests[:4]
        self.input_q = None
        bank = self.row // 4 % 2
        reading = request is not None and request[0] is not None
        if reading:
            group, _, k = request[0]
            bank = group % 2
            assert self.input_owner[bank] == group and group in self.a_ready
            self.input_q = [self.input_banks[bank][r][k] for r in range(min(4,99-4*group))]
            assert all(v is not None for v in self.input_q)
        self.accept_load(inp,reading,bank,self.cycle)
        self.inner += 1
        if emit and emit[1:] == (15,3):
            group = emit[0]
            self.input_owner[group%2] = None
            self.queue.complete(group,self.cycle)
            if self.wave_last > group:
                self.row = 4 * (group+1)
            else:
                self.state = 14
        return self.retire(popped)

    def seed(self, row, col, tile):
        assert self.first_bias is not None and tile == 0
        self.shadow[col//2] = tile, self.decode(self.first_bias)

    def tick(self, inp, control):
        if inp.get('reset'):
            return super().tick(inp,control)
        old = self.state
        if old == 16:
            popped = self.boot(inp,control)
        elif old == 7:
            popped = self.wave(inp,control)
        else:
            popped = super().tick(inp,control)
            if old == 4:
                self.first_bias = self.read_bias(self.chunk)
                self.bias_reads_count['initial'] += 1
        self.advance_correction(self.accepted(inp,old))
        return popped


def save(name, value):
    (REPORT/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def simulate(mode, case, program, initial, first, rows=None):
    if mode == 'M0':
        return frozen.simulate(mode,case,program,initial,first,rows)
    t.staged.patch_parameter_limit(prologue=True)
    core = PairCore(case)
    result = t.simulate('I','response_relative',case,program,initial,first,0,
        make_core=lambda _:core, bootstrap=256, parameter_layout=trb.sg.p2.quartet_layout,
        make_port=partial(frozen.StartupPort,bootstrap=256),
        host_schedule=partial(frozen.startup_host,bootstrap=256),make_wrapper=frozen.ChainWrapper)
    assert core.mac_cycles == [25600]*4 and core.commits == 1600
    assert core.queue.reads == core.queue.writes == 25344
    assert core.correction_counts == dict(input=99*32,weight=256*32)
    result.update(mode=mode,first_operand=core.first_source,prologue_done=core.boot_done_cycle,
        boot_launch=core.boot_launch,join=core.joins,reuse_wait=len(core.reuse_wait),
        seed_wait=core.seed_wait,peak_raw=core.peak_raw,peak_seed_cache=core.peak_boot_cache,
        bias_reads=core.bias_reads_count,bias_correction_writes=core.bias_writes_count,
        corrections=core.correction_counts,output_ready=core.queue.group_ready,output_freed=core.queue.group_freed)
    return result


def main():
    program,initial,first,trace = frozen.observe()
    if sys.argv[1:] == ['smoke']:
        row = simulate('W32',0,program,initial,first)
        print({k:row[k] for k in ('cold_cycles','first_mac','first_operand','last_emit','seed_wait','peak_raw','peak_seed_cache')})
        return
    base = simulate('M0',0,program,initial,first,trace)
    actual = {key:base[key] for key in frozen.ANCHORS}
    passed = actual == frozen.ANCHORS and not base['differences']
    save('calibration.json',dict(passed=passed,actual=actual,native=frozen.ANCHORS,differences=base['differences']))
    assert passed
    print('W32_CALIBRATION',actual,flush=True)
    results = [base]
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = [(mode,case,pool.submit(simulate,mode,case,program,initial,first))
                for mode in ('M0','W32') for case in range(12) if (mode,case)!=('M0',0)]
        for mode,case,job in jobs:
            row=job.result()
            results.append(row)
            print('W32_MODEL',mode,case+1,row['cold_cycles'],flush=True)
    totals={mode:sum(row['cold_cycles'] for row in results if row['mode']==mode) for mode in ('M0','W32')}
    save('model-results.json',dict(totals=totals,threshold=400000,selected=totals['W32']<=400000,rows=results))
    print('W32_DECISION',totals,totals['W32']<=400000,flush=True)


if __name__=='__main__':
    main()

