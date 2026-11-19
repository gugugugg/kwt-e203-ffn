"""Reuse X binaries for S/H; compile only the authorized pair descriptor driver."""
import json
from ffn_joint_power import ROOT, BUILD, load, copy_tree


def build(name):
    manifest = load(name)
    parent = manifest['parent']
    destination = ROOT / 'build/optimization/firmware' / name
    if 'M2' not in manifest['hardware']:
        copy_tree(ROOT / parent['firmware'], destination)
        return destination
    if (destination / 'firmware.json').exists():
        return destination
    if name=='ffn_jp_HM2':
        first=build('ffn_jp_M2')
        copy_tree(first,destination)
        return destination
    from build_ffn_codegen_schedule_firmware import compile_program
    program = BUILD / 'programs' / name
    copy_tree(ROOT / parent['program'], program)
    metadata = json.loads((ROOT / parent['firmware'] / 'firmware.json').read_text())
    macros = ['-DKWU_ROW_GROUP=2' if m == '-DKWU_ROW_GROUP=1' else m for m in metadata['macros']]
    compile_program(program, destination, manifest['compiler'], macros)
    path = destination / 'firmware.json'
    value = json.loads(path.read_text())
    value.update(row_group=2, descriptor_input_words=64, descriptor_output_words=256,
                 tail_input_words=32, tail_output_words=128)
    path.write_text(json.dumps(value, indent=2))
    return destination
