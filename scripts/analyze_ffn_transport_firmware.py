"""Record the actual emitted loops, stack traffic and compact-kernel encodings."""
from pathlib import Path
import re
import sys
from ffn_transport import ROOT, REPORT, load, dump


def analyze(name):
    folder = ROOT / 'build/optimization/firmware' / name
    text = (folder / 'disassembly.txt').read_text()
    functions = {}
    current = None
    for line in text.splitlines():
        match = re.match(r'^([0-9a-f]+) <([^>]+)>:', line)
        if match:
            current = match.group(2)
            functions[current] = []
        elif current and re.match(r'^\s*[0-9a-f]+:', line):
            functions[current].append(line.strip())
    loops = []
    stack = []
    for symbol, lines in functions.items():
        if symbol.startswith('kwu_run_linear') or symbol.startswith('transport_') or symbol.startswith('kwt_transport_'):
            for line in lines:
                if '(sp)' in line:
                    stack.append(dict(function=symbol, instruction=line))
                if re.search(r'\b(bne|bnez|beq|beqz|bltu|bgeu|blt|bge|j)\b', line):
                    loops.append(dict(function=symbol, instruction=line))
    result = dict(variant=name, software=load(name)['software'],
                  compiler_flags='unchanged rv32imac_zicsr_zifencei, ilp32, -O2, no-relax',
                  transport_functions={k:v for k,v in functions.items() if k.startswith('kwt_transport_') or k.startswith('transport_') or k.startswith('kwu_run_linear')},
                  branches=loops, stack_accesses=stack,
                  source_order='Each generated group declares all reads before all writes; volatile MMIO ordering is retained',
                  interpretation='Disassembly evidence, not a cycle or energy measurement')
    dump(REPORT / 'firmware-analysis' / (name + '.json'), result)
    return result


if __name__ == '__main__':
    for name in sys.argv[1:]:
        print('FIRMWARE_DISASSEMBLY_RECORDED', name, len(analyze(name)['stack_accesses']))
