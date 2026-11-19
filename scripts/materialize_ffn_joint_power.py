"""Build every round-seven source from the exact accepted X snapshot."""
import json
from ffn_joint_power import ROOT, REPORT, load, candidates, copy_tree, dump, prove_bias32
from materialize_ffn_loading_dma import add_ports, wires, connections, CHANNELS


def prepare(name):
    manifest = load(name)
    out = ROOT / 'build/optimization/rtl_sources' / name
    copy_tree(ROOT / manifest['parent']['source_snapshot'], out)
    path = out / 'encoder/kwt_encoder.sv'
    text = path.read_text()
    from joint_power_compute import skip_seed, pair_gates
    text = skip_seed(text)
    if 'M2' in manifest['hardware']:
        from joint_power_rowpair import transform_core, transform_wrapper
        text = transform_core(text, 'H' in manifest['hardware'])
        wrapper = out / 'encoder_bus/kwt_icb_encoder.sv'
        wrapper.write_bytes(transform_wrapper(wrapper.read_text()).encode('utf-8'))
        (out / 'encoder/kwt_joint_output_queue.sv').write_bytes((ROOT / 'rtl/joint_power/kwt_joint_output_queue.sv').read_bytes())
    elif 'H' in manifest['hardware']:
        text = pair_gates(text)
    path.write_bytes(text.encode('utf-8'))
    (out/'joint-power-configuration.json').write_bytes(json.dumps(manifest,indent=2).encode('utf-8'))
    return out


def variants():
    return {name: ['PIPE', 'OUTPUT'] for name in candidates()}
