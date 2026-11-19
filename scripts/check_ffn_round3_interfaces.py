"""Exercise the changed pair, overlap and gated FIFO paths using actual FFN tasks."""
import subprocess
import sys
from ffn_round3_config import ROOT

variants=['ffn_v3_I','ffn_v3_NUIT','ffn_v3_NUIGL','ffn_v3_NUITGL']
for variant in variants:
    base=[sys.executable,'scripts/check_optimization_rtl.py',variant,'--linear-only',
          '--package','models/kwt_unified_optimized_v1','--vectors','build/optimization/quantization/Q2_training_range']
    for flags,label in [(['--mixed-output'],'mixed'),(['--skip-build','--stall-output'],'stall'),
                        (['--skip-build','--single-output'],'single')]:
        subprocess.run(base+flags+['--label','round3_'+label],cwd=ROOT,check=True)
