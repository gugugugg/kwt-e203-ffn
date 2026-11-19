"""Local transport development checks, isolated from formal candidate runs."""
from pathlib import Path
from datetime import datetime
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'scripts/server')]
from post_dma_transport import shared_handoff
from bind_ffn_loading_dma_soc import shared_controller


def main():
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out = ROOT/'build/optimization/ffn_post_dma/development'/('transport-'+stamp)
    report = ROOT/'reports/optimization/ffn_post_dma/development'/('transport-'+stamp)
    out.mkdir(parents=True); report.mkdir(parents=True)
    def run(name, command):
        with (report/(name+'.log')).open('w') as stream:
            subprocess.run([str(x) for x in command], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        return (report/(name+'.log')).read_text()
    binary = out/'engine.vvp'
    run('engine-compile', ['iverilog','-g2012','-s','transport_engine_tb','-o',binary,
        ROOT/'rtl/post_dma/kwt_ld_engine.sv',ROOT/'tb/ffn_post_dma/transport_engine_tb.sv'])
    engine = run('engine-run', ['vvp',binary])
    if 'POST_DMA_ENGINE_PASS' not in engine: raise RuntimeError(engine)
    shared = out/'shared.sv';shared.write_text(shared_handoff(shared_controller()))
    binary = out/'shared.vvp'
    run('shared-compile', ['iverilog','-g2012','-s','transport_shared_tb','-o',binary,shared,
        ROOT/'rtl/post_dma/kwt_ld_icb_arbiter.sv',ROOT/'tb/ffn_loading_dma/shared_memory_model.sv',
        ROOT/'tb/ffn_post_dma/transport_shared_tb.sv'])
    shared_result = run('shared-run', ['vvp',binary])
    if 'POST_DMA_SHARED_PASS' not in shared_result: raise RuntimeError(shared_result)
    result = dict(passed=True,scope='local transport RTL and functional SRAM model',
                  engine=engine.strip(),shared=shared_result.strip(),report=report.relative_to(ROOT).as_posix())
    (report/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)


if __name__ == '__main__':main()
