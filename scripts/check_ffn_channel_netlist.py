import json
from pathlib import Path
import re

from benchmark_ffn_channel import BUILD, REPORT, ROOT, build_sim, run


def main():
    sources = ['rtl/kwt_sram16x1024_model.sv', 'rtl/kwt_sram16x128_model.sv', 'rtl/kwt_spmem16.sv',
               'rtl/kwt_requantize.sv', 'rtl/kwt_dot64.sv']
    sources += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / 'rtl/ffn_channel').glob('*.sv'))]
    script = 'read_verilog -sv ' + ' '.join(sources)
    script += '; hierarchy -check -top kwt_icb_ffn_channel; proc; opt; memory_dff; memory_collect; opt_clean; check -assert; stat; write_json build/ffn_ablation/structure.json; write_verilog -noattr build/ffn_ablation/channel_coarse.v'
    run('structure', ['yosys', '-p', script])
    design = json.loads((BUILD / 'structure.json').read_text())
    memories = {}
    multiply_cells = 0

    def walk(name):
        nonlocal multiply_cells
        for cell in design['modules'][name].get('cells', {}).values():
            if cell['type'] == '$mem_v2':
                p = cell['parameters']
                width, depth = int(p['WIDTH'], 2), int(p['SIZE'], 2)
                if width != 16 or depth not in [128, 1024, 4096] or int(p['RD_CLK_ENABLE'], 2) != 1 or int(p['RD_PORTS'], 2) != 1 or int(p['WR_PORTS'], 2) != 1:
                    raise RuntimeError('SRAM shape or synchronous single-port contract changed')
                key = '%dx%d' % (width, depth)
                memories[key] = memories.get(key, 0) + 1
            elif cell['type'] == '$mul':
                multiply_cells += 1
            elif cell['type'] in design['modules']:
                walk(cell['type'])

    walk('kwt_icb_ffn_channel')
    exe = build_sim('coarse')
    results = BUILD / 'coarse_results'
    results.mkdir(exist_ok=True)
    run('coarse-run', [str(exe), '+TASKS=14', '+FIRMWARE=' + str(BUILD / 'D_combined/firmware_itcm.hex'),
        '+RESULT_DIR=' + str(results), '+EXPECTED_READS=11936', '+EXPECTED_WORDS=23872',
        '+IMAGE_DIR=' + str(BUILD / 'channel_images'), '+VECTOR_DIR=' + str(BUILD / 'channel_vectors')])
    text = (REPORT / 'coarse-run.log').read_text()
    records = [{k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)} for line in text.splitlines() if line.startswith('CPU_TASK_PASS')]
    if len(records) != 14 or 'CPU_ALL_PASS tasks=14 ' not in text:
        raise RuntimeError('Incomplete post-coarse-synthesis real-CPU run')
    for task in range(14):
        expected = BUILD / 'channel_vectors' / ('task_%02d_expected.hex' % task)
        if (results / ('task_%02d_codes.hex' % task)).read_text().split() != expected.read_text().split():
            raise RuntimeError('Post-synthesis writeback mismatch')
    record = {'status': 'passed', 'tasks': 14, 'bit_exact_output_words': 354816,
              'memory_instances': memories, 'internal_sram_bytes': sum(int(k.split('x')[0]) * int(k.split('x')[1]) // 8 * v for k, v in memories.items()),
              'generic_multiply_cells': multiply_cells, 'netlist': 'Yosys coarse, unmapped', 'tasks_detail': records}
    (REPORT / 'netlist.json').write_text(json.dumps(record, indent=2))
    print(json.dumps({k: record[k] for k in ['status', 'tasks', 'memory_instances', 'internal_sram_bytes', 'generic_multiply_cells']}, indent=2))


if __name__ == '__main__':
    main()
