"""Record whole-program instructions; LTO may move hot code into main."""
import json
import re
from ffn_c16_efficiency import ROOT, REPORT, dump


def analyze(name):
    folder = ROOT / 'build/optimization/firmware' / name
    metadata = json.loads((folder / 'firmware.json').read_text())
    text = (folder / 'disassembly.txt').read_text()
    functions = {}
    current = None
    for line in text.splitlines():
        match = re.match(r'^[0-9a-f]+ <(.+)>:', line)
        if match:
            current = match.group(1)
            functions[current] = dict(instructions=0, stack_memory=[], calls=[])
        elif current and re.match(r'^\s+[0-9a-f]+:', line):
            item = functions[current]
            item['instructions'] += 1
            if '(sp)' in line:
                item['stack_memory'].append(line.strip())
            if re.search(r'\b(jal|jalr|call)\b', line):
                item['calls'].append(line.strip())
    dump(REPORT / 'firmware-analysis' / (name + '.json'), dict(variant=name,
        compiler=metadata.get('compiler',{'inherited_accepted_configuration':True}), compile_and_link_argv=metadata.get('compile_and_link_argv'),
        functions=functions, whole_program=True, assembly_input_is_not_gimple=True))
