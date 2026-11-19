"""Two independent C16 efficiency models; unchanged arithmetic and physical queue."""
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/column_parallel'))
import timing_model as parent_timing
from core_model import ColumnCore
from native_model import SharedMemory, NativeWrapper

REPORT = ROOT/'reports/optimization/ffn_c16_efficiency/models'
REPORT.mkdir(parents=True, exist_ok=True)


class ControlCore(ColumnCore):
    def tick(self, inp, c):
        handoff = c['quant'] and c['last_emit'] and self.lane == 14 and self.tile < 15
        result = super().tick(inp, c)
        if handoff and not inp.get('reset'):
            self.state, self.inner, self.chunk, self.seed_ready = 6, 0, 0, 0
        return result


# Retain the actual single-port arbitration and response machine. Only the
# same-owner same-direction eligibility changes; old ACK/new accept share an edge.
memory_source = inspect.getsource(SharedMemory).replace('class SharedMemory:', 'class WriteMemory:')
memory_source = memory_source.replace("self.owner_read and grant and b['valid'] and b['read']",
                                    "grant and b['valid'] and self.owner_read == b['read']")
exec(compile(memory_source, str(Path(__file__)), 'exec'))


class WriteWrapper(NativeWrapper):
    def __init__(self):
        super().__init__()
        self.memory = WriteMemory(self)


class ControlWrapper(NativeWrapper):
    pass


source = inspect.getsource(parent_timing.run)
source = source.replace('def run(cls, pacing, layer, prefix, commands):',
                        'def run(cls, pacing, layer, prefix, commands, wrapper_type=NativeWrapper, label=None):')
source = source.replace('wrapper = NativeWrapper()', 'wrapper = wrapper_type()')
source = source.replace('last_commit = ack = None', 'last_commit = ack = first_mac = last_emit = None')
source = source.replace("cc = core.comb(c['core_in'])", "cc = core.comb(c['core_in'])\n        if core.state == 7 and first_mac is None: first_mac = cycle\n        if cc['quant']: last_emit = cycle")
source = source.replace('cold_cycles=last_commit+1,', 'cold_cycles=last_commit+1, first_mac=first_mac, last_emit=last_emit,')
source = source.replace("% (cls.__name__, pacing, layer)", "% (label or cls.__name__, pacing, layer)")
namespace = dict(parent_timing.__dict__)
namespace.update(REPORT=REPORT)
exec(compile(source, str(Path(__file__)), 'exec'), namespace)
run = namespace['run']


def main():
    parent_timing.REPORT = REPORT
    prefix, commands = parent_timing.observed_program()
    results = []
    for label, cls, wrapper in [('B', ColumnCore, NativeWrapper), ('C', ControlCore, NativeWrapper),
                                 ('W', ColumnCore, WriteWrapper)]:
        for layer in range(12):
            path = REPORT/('timing-%s-response_relative-%02d.json' % (label, layer))
            result = json.loads(path.read_text()) if path.exists() else run(cls, 'response_relative', layer, prefix, commands, wrapper, label)
            if label == 'B' and layer == 0:
                expected = dict(cold_cycles=100567, final_physical_commit=100566, final_ack=100568,
                                first_mac=29895, last_emit=100538)
                actual = {k: result[k] for k in expected}
                (REPORT/'baseline-anchor-check.json').write_text(json.dumps(dict(passed=actual==expected,
                    expected_native=expected, actual_model=actual), indent=2))
                if actual != expected: raise RuntimeError('C16 model anchors differ')
            results.append(dict(configuration=label, **result))
    totals = {name: sum(r['cold_cycles'] for r in results if r['configuration']==name) for name in ['B','C','W']}
    eligible = [name for name in ['C','W'] if totals[name]<totals['B']]
    selected = min(eligible, key=lambda name:(totals[name], name!='C')) if eligible else None
    result = dict(passed=True, total_cycles=totals, selected=selected, results=results,
                  arithmetic_outputs_checked=12*3*25344, internal_ready_replayed=False,
                  measured_hardware=False, no_added_state_or_macros=True,
                  selection_rule='Lower aggregate final-commit cycles; tie C; at most one hardware')
    (REPORT/'selection.json').write_text(json.dumps(result, indent=2))
    print('EFFICIENCY_MODEL_SELECTION', json.dumps(dict(total_cycles=totals,selected=selected)), flush=True)


if __name__ == '__main__': main()
