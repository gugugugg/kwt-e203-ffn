"""Identify mapped shift-only logic before attributing its measured power."""
import json
from functools import lru_cache

from prepare import REPORT, ROOT, write

BASE = REPORT / 'activity-mapping/native-review-first'


def collect(name):
    folder = BASE / name
    inventory = json.loads((folder / 'inventory.json').read_text())
    connectivity = json.loads((folder / 'connectivity.json').read_text())
    cells = inventory['cells']
    pins = connectivity['pins']
    reps = connectivity['representatives']
    drivers = connectivity['drivers']
    stem = next(key.split('shifts_reg_', 1)[0] for key in cells if '/core/shifts_reg_' in key)
    if name.endswith('_SS'):
        role = 'shared_shift_update_output'
        selected = {key for key, cell in cells.items() if key.startswith(stem)
                    and any(pin in ('Z', 'ZN') and value.strip().startswith('ss_shift_columns_')
                            and value.strip().endswith('__shift_update') for pin, value in cell['pins'].items())}
        assert len(selected) == 8
    else:
        role = 'shift_encoder_identified'
        visited = set()
        selected = set()

        @lru_cache(maxsize=None)
        def walk(net):
            if net is None:
                return False, False
            if net.strip() in ("1'b0", "1'b1"):
                return True, False
            matches = drivers.get(reps.get(net, net), [])
            if len(matches) != 1:
                return False, False
            driver = matches[0]
            key = driver['cell']
            if key.startswith(stem + 'jp_shift_return_reg_'):
                return True, True
            if (not key.startswith(stem) or '/' in key[len(stem):]
                    or not key.rsplit('/', 1)[-1].startswith('U') or key in visited):
                return False, False
            visited.add(key)
            inputs = [walk(pins.get(key + '/' + pin, raw)) for pin, raw in cells[key]['pins'].items()
                      if pin != driver['pin']]
            visited.remove(key)
            pure = bool(inputs) and all(value[0] for value in inputs)
            contains_shift = any(value[1] for value in inputs)
            if pure and contains_shift:
                selected.add(key)
            return pure, contains_shift

        for key in cells:
            if key.startswith(stem + 'shifts_reg_'):
                walk(pins[key + '/D'])
        assert selected
    rows = [dict(cell=key, ref=cells[key]['ref'], pins=cells[key]['pins']) for key in sorted(selected)]
    evidence = dict(tag=inventory['tag'], role=role, identifiable_only=True, cells=rows)
    write(folder / 'separable-shift-power.json', evidence)
    return evidence


def main():
    rows = [collect(name) for name in ('ffn_sra_S3', 'ffn_sra_SS')]
    lines = ['set sra_extra_roles [dict create]']
    for row in rows:
        lines.append('if {$env(XPIAN_TAG) eq "%s"} {' % row['tag'])
        lines.extend('    dict set sra_extra_roles {%s} %s' % (cell['cell'], row['role'])
                     for cell in row['cells'])
        lines.append('}')
        print(row['tag'], row['role'], len(row['cells']), flush=True)
    (ROOT / 'scripts/server/sr_area_power_roles.tcl').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
