"""Exercise a Q4 split commit when an older row fills the second-row stash."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screen import Q4Core, save


def main():
    core = Q4Core()
    # Older row1 results occupy the stash. Their paired synchronous return
    # releases two places on the edge after the new row0 has been accepted.
    core.state, core.row, core.tile = 8, 2, 0
    core.item = core.queue.retired = 256
    core.queue.row1_count = 256
    core.queue.row1 = [(256 + i, i) for i in range(256)]
    core.return_pair = (1, 0)
    for lane in (0,1,16,17):
        core.products[lane] = 64
        core.seeds[lane] = 1
        core.lane_shift[lane] = core.shifts[lane % 16]
    c = core.comb({})
    if not (c['q']['row0_push'] and c['q']['read1_pair'] and not c['q']['row1_push']):
        raise RuntimeError('Q4 failed to accept row0 alone while issuing old row1 read')
    core.tick({}, c)
    if (core.emit_row,core.lane,core.return_pair)!=(1,0,(1,0)):
        raise RuntimeError('Q4 changed column pair or synchronous seed return too early')
    c = core.comb({})
    if not (c['q']['row1_push'] and not c['q']['row0_push'] and c['last_emit']):
        raise RuntimeError('Q4 failed to retire the sole remaining row1 pair')
    core.tick({}, c)
    if (core.emit_row,core.lane,core.return_pair)!=(0,2,(1,1)) or core.queue.fifo_write!=2:
        raise RuntimeError('Q4 repeated row0 or lost column-pair completion')
    save('model-partial-commit.json',dict(passed=True, row0_edge=0, row1_edge=1,
         stimulus='Older row1 stash full with new row0 ready, then a two-word SRAM return',
         row0_submissions=1, row1_submissions=1, next_column=2))


if __name__=='__main__':
    main()
