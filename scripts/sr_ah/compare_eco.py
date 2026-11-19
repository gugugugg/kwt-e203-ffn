"""Verify that the archived AH ECO netlists differ only by planned cell references."""
import json
from pathlib import Path
import re

from prepare import REPORT, dump


def read_netlist(root, tag):
    path = root/'build/server'/('complete_soc_sm40_'+tag)/'netlist.v'
    text = re.sub(r'/\*.*?\*/|//[^\r\n]*', '', path.read_text(), flags=re.S)
    return text


def module_parts(text):
    chunks = re.split(r'(?m)(?=^module kwt_encoder_ACC_ICG_UPDATE1\s*\(|^endmodule\b)', text)
    core = [i for i, part in enumerate(chunks)
            if part.startswith('module kwt_encoder_ACC_ICG_UPDATE1 ')]
    if len(core) != 1:
        raise RuntimeError('AH core module is ambiguous')
    return chunks, core[0]


def normalize(parts):
    return re.sub(r'\s+', '', ''.join(parts))


def main():
    root = REPORT/'received/eco-screen/native-evidence'
    report = root/'reports/optimization/ffn_sr_ah'
    output = []
    for label in ('eco1', 'eco2'):
        folder = report/'eco'/label
        change = json.loads((folder/'planned-sizes.json').read_text())
        previous, index = module_parts(read_netlist(root, change['previous']))
        current_text = read_netlist(root, change['current'])
        current, current_index = module_parts(current_text)
        for row in change['rows']:
            inst = row['cell'].rsplit('/', 1)[1]
            pattern = r'(?m)(^\s*)'+row['old']+r'(\s+'+inst+r'\s*\()'
            previous[index], count = re.subn(pattern, r'\g<1>'+row['new']+r'\g<2>', previous[index])
            if count != 1:
                raise RuntimeError('AH sizing did not match the prior netlist: '+inst)
        if normalize(previous) != normalize(current):
            raise RuntimeError('AH netlist differs beyond the planned references: '+label)
        net_violations = {}
        violation_text = (folder/'constraints.rpt').read_text()
        if 'max_transition' in violation_text:
            pins = re.findall(r'(?m)^\s+\S+/core/(\w+)/(\w+)\s*\n[^\n]*\(VIOLATED\)', 
                              violation_text.split('max_transition',1)[1])
            for inst, pin in pins:
                cell = re.search(r'(?ms)^\s*\w+_12TR40\s+'+inst+r'\s*\((.*?)\)\s*;',current[current_index])
                net = re.search(r'\.'+pin+r'\s*\(\s*(\w+)\s*\)',cell[1])[1]
                net_violations.setdefault(net,[]).append(inst+'/'+pin)
        output.append(dict(batch=label, normalized_netlist_matches=True, sized=len(change['rows']),
                           electrical_pins_by_net=net_violations))
    dump(REPORT/'eco-netlist-comparison.json', dict(batches=output))
    print('AH_ECO_NETLIST_VERIFIED', [item['sized'] for item in output])


if __name__ == '__main__':
    main()
