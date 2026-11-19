"""Fixed2x16 synchronous control/data model derived from the calibrated IR core."""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/taskflow_study'))
from model import Core, OutputQueue, vectors, signed, rne

# The queue and external handshake rules are retained byte-for-byte by import.
source = inspect.getsource(Core)
changes = [
    ('class Core:', 'class ColumnCore:'),
    ('[0] * 16', '[0] * 32'),
    ('range(16)', 'range(32)'),
    ('divmod(lane, 8)', 'divmod(lane, 16)'),
    ('self.emit_row * 8', 'self.emit_row * 16'),
    ('self.tile * 8', 'self.tile * 16'),
    ('target_tile * 8', 'target_tile * 16'),
    ('lane % 8', 'lane % 16'),
    ('lane // 8', 'lane // 16'),
    ('self.tile < 31', 'self.tile < 15'),
    ('self.tile == 31', 'self.tile == 15'),
    ('% 32', '% 16'),
    ('self.lane == 6', 'self.lane == 14'),
    ('self.lane < 6', 'self.lane < 14'),
    ('self.chunk == 3', 'self.chunk == 7'),
]
for old, new in changes:
    source = source.replace(old, new)
exec(compile(source, str(Path(__file__)), 'exec'))


class SerialColumnCore(ColumnCore):
    """Model-only32-state8+8 control: each inner consumes two physical MAC beats."""
    def reset(self):
        super().reset()
        self.half = 0

    def capacity(self, kind):
        prefetch = self.state == 7 and self.half == 1 and self.inner < 63
        read = (self.state == 6 and self.complete()) or prefetch
        return (self.state == 2 and kind in [1, 5]) or (kind == 0 and self.state >= 3 and
            self.input_count < 6336 and self.input_count < (self.row + 4) * 64 and not read)

    def comb(self, inp):
        c = super().comb(inp)
        if self.state == 7:
            c['mac_mask'] &= 0x00ff00ff << (self.half * 8)
        return c

    def tick(self, inp, c):
        old_state, old_inner, half = self.state, self.inner, self.half
        popped = super().tick(inp, c)
        if old_state == 7:
            self.half = 1 - half
            if half == 0:
                self.state, self.inner = old_state, old_inner
        return popped
