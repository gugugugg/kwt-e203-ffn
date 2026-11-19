"""Write a compact two-column stimulus fixture from the causal case-one replay."""
import importlib.util

from common import ROOT, WORK, write_json
spec = importlib.util.spec_from_file_location("paired_model", ROOT / "scripts/trb_pair_mac/model.py")
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def main():
    startup, _ = model.wide.calibrated_startup()
    task = model.PairedTask(0, startup)
    result = task.run()
    assert result["complete"]
    vectors = model.wide.base.baseline.q16.q8.m3.r3o.vectors(0)
    inputs, weights, bias, shifts = (list(map(int, values)) for values in vectors)
    units = []
    for first_edge, columns in task.slice_events.items():
        slot, k, _, _ = columns[0]
        if k == 0 and slot.group % 2 == 0:
            units.append([first_edge, slot.tile, slot.group])
    assert len(units) == 104
    row_adjust = [-sum(inputs[row*64+k]*inputs[row*64+k+1] for k in range(0,64,2)) for row in range(99)]
    narrow_weights = [[weights[256*k+32*tile+col] for k in range(64) for col in (0,16)] for tile in range(8)]
    narrow_bias = [[bias[32*tile+col] for col in (0,16)] for tile in range(8)]
    narrow_shift = [[shifts[32*tile+col] for col in (0,16)] for tile in range(8)]
    outputs = [[task.golden[256*row+32*tile+col] for row in range(99) for col in (0,16)] for tile in range(8)]
    write_json(WORK/"slice-compact.json", dict(
        cycles=result["cold_cycles"], units=units, x=inputs, w=narrow_weights,
        bias=narrow_bias, shifts=narrow_shift, row_adjust=row_adjust, y=outputs,
    ))
    correction = [[cycle, [item[:3] for item in operations]]
                  for cycle, operations in task.correction_events.items()]
    emit = []
    for cycle, events in task.slice_events.items():
        slot, k, _, _ = events[0]
        if k == 63:
            emit.extend([cycle+4+2*col, slot.tile, col, slot.group % 2] for col in range(16))
    write_json(WORK/"correction-compact.json", dict(cycles=result["cold_cycles"],
               operations=correction, reads=task.correction_reads, emits=sorted(emit)))


if __name__ == "__main__":
    main()

