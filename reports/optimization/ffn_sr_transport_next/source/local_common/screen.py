"""Screen SR, PRF, W1 and their combination against the observed cold task."""
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_sr_transport_next'
sys.path.insert(0, str(ROOT / 'scripts/sr_pr1'))
import model_screen as sr
from transport import Engine

VARIANTS = ('SR', 'PRF', 'W1', 'PRF_W1')


def output_address(address):
    return 0xa0010000 <= address < 0xa001c600 and address % 4 == 0


class EarlyMemory(sr.WriteMemory):
    def __init__(self, wrapper):
        super().__init__(wrapper)
        self.pending_early = False
        self.fast_returns = self.fast_turnovers = 0
        self.early_reads = self.early_writes = 0

    def qualifies(self, cmd):
        if cmd['read']:
            return self.wrapper.prf and sr.parameter_read(cmd)
        return self.wrapper.w1 and output_address(cmd['address'])

    def comb(self):
        c = super().comb()
        if self.pending_early:
            retire = c['rsp_ready']
            handoff = (retire and c['grant'] and c['b']['valid']
                       and self.owner_read == c['b']['read'] and self.qualifies(c['b'])
                       and not c['host']['valid'] and not self.host_valid)
            c.update(valid=True, data=self.memory_data if self.read_pending else 0,
                     retire=retire, available=handoff, joined_valid=handoff,
                     joined_ready=handoff, ready=handoff, fire=handoff,
                     physical=handoff, write=handoff and not self.read_pending)
        return c

    def tick(self, command, response_ready, cycle):
        c = self.current
        old_early = self.pending_early
        next_early = bool(c['fire'] and c['grant'] and self.qualifies(c['selected']))
        if old_early:
            # Consume the old response, or transfer it into the ordinary holding
            # register once. The new physical operation can now set pending.
            self.pending = 0
            self.current_valid = True
            if c['rsp_ready']:
                self.fast_returns += 1
                self.fast_turnovers += int(c['fire'])
                self.early_reads += int(self.read_pending)
                self.early_writes += int(not self.read_pending)
        super().tick(command, response_ready, cycle)
        if old_early and not c['rsp_ready']:
            self.valid, self.data = 1, c['data']
        self.pending_early = next_early


class CreditEngine(Engine):
    def __init__(self, wrapper):
        super().__init__()
        self.wrapper = wrapper
        self.returned_credit = False

    def commands(self, input_ready, output_ready):
        cmds = super().commands(input_ready, output_ready)
        if self.returned_credit:
            if self.output_transfer:
                cmds['pio']['valid'] = int(output_ready and not self.pd_source_pending)
            else:
                cmds['memory']['valid'] = 1
        return cmds


class TransportWrapper(sr.WriteWrapper):
    def __init__(self, variant):
        super().__init__()
        self.prf = variant in ('PRF', 'PRF_W1')
        self.w1 = variant in ('W1', 'PRF_W1')
        self.engine = CreditEngine(self)
        self.engine.address = self.engine.done = self.engine.pd_source_slot = 0
        self.memory = EarlyMemory(self)
        self.credit_edges = 0

    def comb(self, cpu):
        e = self.engine
        e.returned_credit = False
        c = super().comb(cpu)
        if e.pd_active and e.pd_count == 2 and e.source_remaining:
            if e.output_transfer:
                # A shared ACK for an already accepted write is independent
                # of a new PIO read and of that read's ready.
                e.returned_credit = (self.w1 and output_address(e.address - 4)
                                     and e.pd_dest_pending and c['memory']['valid'])
            else:
                pio = c['pio_return']
                e.returned_credit = (self.prf and sr.parameter_read(c['commands']['memory'])
                                     and pio['valid'] and (e.pd_dest_pending or
                                         c['commands']['pio']['valid'] and pio['ready']))
        return super().comb(cpu) if e.returned_credit else c

    def tick(self, cpu, c, cycle):
        e = self.engine
        if e.returned_credit:
            src = 'pio' if e.output_transfer else 'memory'
            ready = c['pio_return' if e.output_transfer else 'memory']['ready']
            self.credit_edges += int(c['commands'][src]['valid'] and ready)
        result = super().tick(cpu, c, cycle)
        if e.pd_count > 2:
            raise RuntimeError('More than two DMA slots reserved at cycle %d' % cycle)
        return result


def simulate(variant, pacing, case, prefix, commands, prior_response):
    wrapper = TransportWrapper(variant)
    # Reuse the frozen replay/golden checks without changing the earlier PR1
    # script or its archived model. Only the transport instance is replaced.
    replay = FunctionType(sr.simulate.__code__, dict(sr.simulate.__globals__,
                         WriteWrapper=lambda: wrapper))
    result = replay(variant, pacing, case, prefix, commands, prior_response)
    result.update(early_reads=wrapper.memory.early_reads,
                  early_writes=wrapper.memory.early_writes, full_credit_edges=wrapper.credit_edges)
    return result


def save(name, result):
    (REPORT / name).write_text(json.dumps(result, indent=2) + '\n')


def main():
    prefix, commands, prior_response, observed = sr.read_program()
    baseline = simulate('SR', 'response_relative', 0, prefix, commands, prior_response)
    matches = {key: baseline[key] == value for key, value in sr.ANCHORS.items()}
    for model, native in [('parameter_read_cycles', 'parameter_accepts'),
                          ('parameter_return_cycles', 'parameter_returns'),
                          ('parameter_pio_cycles', 'parameter_pio_writes')]:
        matches[model] = baseline[model] == [edge[0] for edge in observed[native]]
    save('calibration.json', matches)
    if not all(matches.values()):
        raise RuntimeError('SR model differs from native trace')
    results = {name: {} for name in VARIANTS}
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = [(variant, pacing, case, pool.submit(simulate, variant, pacing, case,
                  prefix, commands, prior_response))
                for pacing in ('response_relative', 'fixed_cpu')
                for variant in VARIANTS for case in range(12)]
        for variant, pacing, case, job in jobs:
            result = job.result()
            save('%s-%s-%02d.json' % (variant, pacing, case+1), result)
            row = {key: value for key, value in result.items() if not isinstance(value, list)}
            results[variant].setdefault(pacing, []).append(row)
            print(variant, pacing, case+1, row['cold_cycles'], row['final_ack'],
                  row['early_reads'], row['early_writes'], row['full_credit_edges'], flush=True)
    totals = {variant: sum(row['cold_cycles'] for row in cases['response_relative'])
              for variant, cases in results.items()}
    # A tie favors PRF to preserve the cold-start focus of this round.
    best = min(('PRF', 'W1'), key=totals.get)
    winner = 'PRF_W1' if totals['PRF_W1'] < totals[best] else best
    if totals[winner] >= totals['SR']:
        winner = None
    save('model-results.json', dict(cycles_total=totals, winner=winner, results=results,
                                    based_on='SR native case1 plus frozen 12-task images',
                                    measured_hardware=False))
    print('TRANSPORT_MODEL_SELECTION', totals, winner, flush=True)


if __name__ == '__main__':
    main()
