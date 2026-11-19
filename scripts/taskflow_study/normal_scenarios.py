"""Normal core-model interface cases: scalar, odd paired reads, pause and reload."""
import json
import struct
from model import ROOT, REPORT, Core, vectors


def run(label):
    core = Core(initial_state=1)
    layer = 0
    frame_results = []
    frame_outputs = []
    pause_remaining = 0
    paused = False
    expected = [x[0] for x in struct.iter_unpack('<h',
        (ROOT / 'build/optimization/ffn_transport/testdata/linear_00_expected.bin').read_bytes())]
    for cycle in range(600000):
        inp = dict(out_ready=False, out_pair_ready=False)
        if core.state == 1:
            inp['start'] = True
        elif core.state == 2:
            if core.parameter_count < 17408:
                inp.update(load=True, load_kind=1, load_address=core.parameter_count, load_pair=True)
            elif core.shift_count < 128:
                inp.update(load=True, load_kind=5, load_address=core.shift_count, load_pair=False)
            else:
                inp['layer_start'] = True
        elif core.capacity(0) and core.input_count < 6336:
            inp.update(load=True, load_kind=0, load_address=core.input_count, load_pair=False)
        if label == 'mixed_paused' and not paused and len(frame_outputs) >= 512:
            paused, pause_remaining = True, 4096
        if pause_remaining:
            pause_remaining -= 1
        elif core.queue.held:
            single = label == 'single' or core.item % 17 == 0 or core.item == 25343
            inp['out_ready'] = single
            inp['out_pair_ready'] = not single and len(core.queue.held) == 2
        c = core.comb(inp)
        popped = core.tick(inp, c)
        for index, value in popped:
            if index != len(frame_outputs) or value != expected[index]:
                raise RuntimeError('Normal model scenario output differs: %s layer%d item%d' % (label, layer, index))
            frame_outputs.append(value)
        if len(frame_outputs) == 25344:
            frame_results.append(dict(layer=layer, outputs=25344, ordered=True, exact_values=True,
                                      queue_peak=dict(core.queue.peak), pause_cycles=4096 if paused else 0))
            if layer == 1:
                break
            layer = 1
            core.x, core.w, core.bias, core.shifts = vectors(layer)
            frame_outputs, paused = [], False
            expected = [x[0] for x in struct.iter_unpack('<h',
                (ROOT / 'build/optimization/ffn_transport/testdata/linear_01_expected.bin').read_bytes())]
    else:
        raise RuntimeError('Normal model scenario did not finish: ' + label)
    result = dict(scenario=label, passed=True, continuous_frames=frame_results,
                  cycles=cycle + 1, scope='Core model contract tests; original RTL three-scenario evidence remains separate')
    (REPORT / ('normal-model-' + label + '.json')).write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    results = []
    for label in ['single', 'mixed', 'mixed_paused']:
        path = REPORT / ('normal-model-' + label + '.json')
        results.append(json.loads(path.read_text()) if path.exists() else run(label))
    (REPORT / 'normal-model-scenarios.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
