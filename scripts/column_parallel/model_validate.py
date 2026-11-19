"""IR native-trace calibration and normal12-layer column-model validation."""
import json
import sys
import numpy as np
from core_model import ROOT, ColumnCore, SerialColumnCore, vectors, source
import native_model

REPORT = ROOT / 'reports/optimization/ffn_column_parallel/models'
REPORT.mkdir(parents=True, exist_ok=True)


def normal(cls, scenario):
    core = cls()
    frames, output = [], []
    for layer in range(12):
        core.x, core.w, core.bias, core.shifts = vectors(layer)
        sums = np.array(core.x, dtype=np.int64).reshape(99, 64) @ np.array(core.w, dtype=np.int64).reshape(64, 256)
        sums += np.array(core.bias, dtype=np.int64)
        from model import rne
        expected = [rne(int(v), core.shifts[i % 256]) for i, v in enumerate(sums.reshape(-1))]
        output = []
        pause, paused = 0, False
        counts = dict(mac_clocks=0, contributions=0, quant_pairs=0, blocked=0, input_missing=0)
        for cycle in range(1000000):
            inp = dict(out_ready=False, out_pair_ready=False)
            if core.state == 1: inp['start'] = True
            elif core.state == 2:
                if core.parameter_count < 17408: inp.update(load=True, load_kind=1, load_address=core.parameter_count, load_pair=True)
                elif core.shift_count < 128: inp.update(load=True, load_kind=5, load_address=core.shift_count)
                else: inp['layer_start'] = True
            elif core.capacity(0) and core.input_count < 6336:
                inp.update(load=True, load_kind=0, load_address=core.input_count)
            if scenario == 'mixed_paused' and not paused and len(output) >= 512:
                paused, pause = True, 4096
            if pause: pause -= 1
            elif core.queue.held:
                single = scenario == 'single' or core.item % 17 == 0 or core.item == 25343
                inp['out_ready'] = single
                inp['out_pair_ready'] = not single and len(core.queue.held) == 2
            c = core.comb(inp)
            counts['mac_clocks'] += core.state == 7
            counts['contributions'] += c['mac_mask'].bit_count()
            counts['quant_pairs'] += c['quant']
            counts['blocked'] += core.state == 8 and not c['quant']
            counts['input_missing'] += core.state in [6, 15] and not core.complete()
            for index, value in core.tick(inp, c):
                if index != len(output) or value != expected[index]:
                    raise RuntimeError('Output identity/value differs: %s %d %d' % (scenario, layer, index))
                output.append(value)
            if len(output) == 25344: break
        else: raise RuntimeError('Normal model did not finish')
        frames.append(dict(layer=layer, cycles=cycle+1, outputs=len(output), exact=True, ordered=True,
                           counts=counts, queue_peak=dict(core.queue.peak)))
        print('COLUMN_MODEL_PASS', cls.__name__, scenario, layer, cycle+1, flush=True)
    result = dict(passed=True, model=cls.__name__, scenario=scenario, frames=frames,
                  hardware_measured=False, scope='Local core/queue functional model; not full E203 cold timing')
    (REPORT / (cls.__name__+'-'+scenario+'.json')).write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    native_model.REPORT = REPORT
    if not (REPORT/'native-M0-validation.json').exists():
        if not native_model.validate()['passed']: raise RuntimeError('IR calibration failed')
    (REPORT/'column-core-model.py.txt').write_text(source)
    for cls in [ColumnCore, SerialColumnCore]:
        for scenario in ['actual12', 'mixed_paused', 'single']:
            path = REPORT/(cls.__name__+'-'+scenario+'.json')
            if not path.exists(): normal(cls, scenario)
