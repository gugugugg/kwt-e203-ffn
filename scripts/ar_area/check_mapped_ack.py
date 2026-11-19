"""Check the final physical response-ready cone against the original arbiter."""
from itertools import product
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from ffn_ar_area import REPORT, dump

PRIMITIVE = re.compile(r'^\s*(buf|not|and|nand|or|nor|xor|xnor)\s+\w+\s*\(([^;]+)\);',re.M)


def evaluate_gate(op, args):
    if op == 'buf':
        return args[0]
    if op == 'not':
        return not args[0]
    if op in ('and','nand'):
        return all(args) if op=='and' else not all(args)
    if op in ('or','nor'):
        return any(args) if op=='or' else not any(args)
    result = sum(args)%2 == 1
    return result if op=='xor' else not result


def check(name):
    folder = REPORT/'activity-mapping/native-review-first'/name
    inventory = json.loads((folder/'inventory.json').read_text())
    cells = inventory['cells']
    vendor = (folder/'vendor-functions.v').read_text()
    models = {m[1]:m[0] for m in re.finditer(r'module\s+(\w+)\b.*?endmodule',vendor,re.S)}
    prefix = 'shared_memory/memory_arbiter/'
    gate_cells = {path:{k:v.strip() for k,v in cell['pins'].items()}
                  for path,cell in cells.items() if path.startswith(prefix) and path.count('/')==2}
    drivers = {net:(path,pin) for path,pins in gate_cells.items() for pin,net in pins.items()
               if pin in ('Z','ZN','Q','QN')}
    evidence = {}
    boundaries = ['active','owner','held_valid','held_owner','prefer_b',
                  'a_cmd_valid_BAR','b_cmd_valid','a_rsp_ready','b_rsp_ready']
    for net in boundaries[:5]:
        path,pin = drivers[net]
        assert pin=='Q' and cells[path]['ref']=='DRNQV6_12TR40'
        evidence[path] = dict(cell=cells[path],model=models[cells[path]['ref']].split('specify')[0])

    def compute(net, values):
        if net in values:
            return values[net]
        path,output = drivers[net]
        pins = gate_cells[path]
        model = models[cells[path]['ref']].split('specify')[0]
        evidence[path] = dict(cell=cells[path],model=model)
        internal = {}
        for op, raw in PRIMITIVE.findall(model):
            dest, *sources = [x.strip() for x in raw.split(',')]
            args = [internal[s] if s in internal else compute(pins[s],values) for s in sources]
            internal[dest] = evaluate_gate(op,args)
        values[net] = internal[output]
        return values[net]

    for inputs in product([False,True],repeat=len(boundaries)):
        active,owner,hv,ho,pref,abar,bvalid,ar,br = inputs
        grant = ho if hv else bvalid and (abar or pref)
        recipient = owner if active else grant
        assert compute('s_rsp_ready',dict(zip(boundaries,inputs))) == (br if recipient else ar)
    state = cells['shared_memory/joined_rsp_valid_reg']
    assert state['ref']=='DRNQV6_12TR40' and state['pins']['Q'].strip()=='joined_rsp_valid'
    assert cells['shared_memory/memory_arbiter']['pins']['s_rsp_ready'].strip()=='joined_rsp_ready'
    source = ROOT/'build/optimization/complete_soc'/name/'kwt_shared_dma_icb_sm40.sv'
    assert 'assign s_rsp_ready=recipient?b_rsp_ready:a_rsp_ready;' in source.read_text()
    dump(folder/'mapped-ack-interface.json',dict(passed=True,variant=name,tag=inventory['tag'],
         valid_expression='dut.shared_memory.joined_rsp_valid',ready_expression='dut.shared_memory.joined_rsp_ready',
         valid_evidence=state,ready_evidence=evidence,truth_table_cases=512,truth_table_mismatches=0,
         original_source=source.relative_to(ROOT).as_posix()))
    print('ARA_MAPPED_ACK_CONE',name,len(evidence),512,flush=True)


if __name__=='__main__':
    for name in sys.argv[1:]:
        check(name)
