"""Bind the accepted frozen core's phases to the new candidate's physical pins and SAIF."""
from collections import defaultdict
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SR = ROOT / 'reports/optimization/ffn_ar_area/activity-mapping/native-review-first/ffn_ara_SR'
CORE = 'soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core/'


def read(folder, name):
    return json.loads((folder / name).read_text())


def bridge(folder):
    source = read(SR, 'inventory.json')
    target = read(folder, 'inventory.json')
    old_conn = read(SR, 'connectivity.json')
    new_conn = read(folder, 'connectivity.json')
    activity = read(folder, 'saif-index.json')['activity']
    source_draft = read(SR, 'corrections-draft.json')
    source_cells = {row['rtl']: row for row in read(SR, 'physical-cell-phase-review.json')}
    draft = read(folder, 'corrections-draft.json')
    old_core = {path: cell for path, cell in source['cells'].items()
                if path.startswith(CORE) and path not in source['hierarchy']}
    new_core = {path: cell for path, cell in target['cells'].items()
                if path.startswith(CORE) and path not in target['hierarchy']}
    assert set(new_core) - set(old_core) == {CORE + 'I_0'} and set(old_core) <= set(new_core)
    adapter = new_core[CORE + 'I_0']
    assert adapter['ref'] == 'CLKINV2_12TR40'
    assert {pin: expr.strip() for pin, expr in adapter['pins'].items()} == {
        'I': 'out_index_8__BAR', 'ZN': 'out_index[8]'}

    pairs = defaultdict(list)
    old_reps, new_reps = old_conn['representatives'], new_conn['representatives']
    for path, cell in old_core.items():
        new_cell = new_core[path]
        assert new_cell['ref'] == cell['ref'] and new_cell['pins'].keys() == cell['pins'].keys()
        for pin in cell['pins']:
            qualified = path + '/' + pin
            previous = old_conn['pins'].get(qualified)
            measured = new_conn['pins'].get(qualified)
            if previous is not None and measured is not None and "'" not in previous + measured:
                pairs[old_reps.get(previous, previous)].append((qualified, measured))

    native = {row['rtl']: row for row in target['mappings']}
    rules = {row['rtl']: row for row in source['mappings'] if row['rtl'].startswith(CORE)}
    rules.update({row['rtl']: row for row in source_draft['aliases'] if row['rtl'].startswith(CORE)})
    suppressed = set(source_draft['suppressed_opposite_phase_aliases']) | set(
        source_draft.get('deduplicated_positive_aliases', []))
    restored, unresolved, retained = [], [], []
    for rtl, rule in rules.items():
        if rtl not in activity or rtl in suppressed:
            continue
        if rule.get('cell'):
            path = rule['gate']
            if path not in old_core:
                unresolved.append(dict(rtl=rtl, reason='cell is outside the matched leaves'))
                continue
            review = source_cells.get(rtl)
            pin = review['output'] if review else 'Q'
            qualified = path + '/' + pin
            measured = new_conn['pins'].get(qualified)
            if measured is None:
                unresolved.append(dict(rtl=rtl, reason='no matched leaf output'))
                continue
            inverted = review['physical_inverted'] if review else rule['inverted']
            pair = (qualified, measured)
        else:
            previous = rule['gate']
            choices = pairs.get(old_reps.get(previous, previous), [])
            if len({new_reps.get(net, net) for _, net in choices}) != 1:
                unresolved.append(dict(rtl=rtl, previous=previous,
                                       reason='no unique pin-connected final segment'))
                continue
            pair = min(choices, key=lambda item: (len(item[1]), item[1], item[0]))
            inverted = rule['inverted']
        qualified, measured = pair
        if rtl in native:
            rule_now = native[rtl]
            assert rule_now['cell'] and not rule_now['inverted'] and not inverted
            assert qualified == rule_now['gate'] + '/Q'
            retained.append(rtl)
            continue
        restored.append(dict(rtl=rtl, gate=measured, inverted=inverted,
                             reason='The accepted phase follows the identical physical leaf/pin '
                                    'onto the actual new final segment and uses new cold-task SAIF.',
                             evidence=dict(matched_pin=qualified, old_gate=rule['gate'],
                                           physical_reference=new_core[qualified.rsplit('/', 1)[0]]['ref'])))

    assert restored and len(retained) == len([rtl for rtl in native if rtl.startswith(CORE)])
    draft['aliases'].extend(restored)
    (folder / 'corrections-draft.json').write_text(json.dumps(draft, indent=2) + '\n')
    record = dict(source_tag=source['tag'], target_tag=target['tag'], matched_leaf_instances=len(old_core),
                  library_adapter=adapter, restored_rules=len(restored), retained_native_rules=retained,
                  unresolved=unresolved, new_SAIF_only=True, unknown_zero_filled=False)
    (folder / 'frozen-core-activity-bridge.json').write_text(json.dumps(record, indent=2) + '\n')
    print('SR_DMA_CORE_ACTIVITY_BRIDGE', len(old_core), len(restored), len(unresolved), flush=True)


if __name__ == '__main__':
    bridge(Path(sys.argv[1]))
