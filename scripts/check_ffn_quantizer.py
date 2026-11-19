from pathlib import Path
import subprocess
import shutil
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.fixed_ops import round_shift, saturate16
out = ROOT / 'build/optimization/ffn_round2/quantizer'
obj = out / 'obj'
out.mkdir(parents=True, exist_ok=True)
values = []
for shift in range(13, 19):
    inputs = {-(1 << 63), (1 << 63)-1, -(1 << 35), (1 << 35)-1, -1, 0, 1}
    for quotient in [-32769,-32768,-32767,-2,-1,0,1,2,32766,32767,32768]:
        for remainder in [0, (1 << (shift-1))-1, 1 << (shift-1), (1 << (shift-1))+1, (1 << shift)-1]:
            inputs.add(quotient*(1 << shift)+remainder)
    for value in sorted(inputs):
        expected = int(saturate16(round_shift(np.int64(value), shift)))
        values.append((value, shift, expected))
vectors = out / 'vectors.txt'
vectors.write_text(''.join('%d %d %d\n' % v for v in values))
def run(cmd):
    with (out / 'build.log').open('a') as log:
        subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
run(['verilator_bin','--cc','--Wno-fatal','--top-module','kwt_ffn_quantizer_check','--Mdir',str(obj),
     'rtl/kwt_requantize.sv','rtl/ffn/kwt_ffn_requantize.sv','tb/ffn/quantizer_check.sv'])
include = ROOT / 'tools/oss-cad-suite/share/verilator/include'
sources = sorted(obj.glob('Vkwt_ffn_quantizer_check*.cpp')) + [ROOT/'tb/ffn/quantizer_check.cpp',include/'verilated.cpp',include/'verilated_threads.cpp']
objects = []
for source in sources:
    dest = out / (source.stem + '.o')
    run([shutil.which('g++'),'-std=c++20','-O2','-pthread','-DVL_TIME_CONTEXT','-DVM_COVERAGE=0','-DVM_TRACE=0','-DVM_TIMING=0',
         '-I'+str(include),'-I'+str(include/'vltstd'),'-I'+str(obj),'-c',str(source),'-o',str(dest)])
    objects.append(str(dest))
exe = out / 'check.exe'
run([shutil.which('g++'),'-static','-pthread']+objects+['-o',str(exe)])
result = subprocess.check_output([str(exe),str(vectors)],cwd=ROOT,text=True)
report = ROOT / 'reports/optimization/ffn_round2/quantizer-check.json'
report.write_text(json.dumps({'passed': True,'cases': len(values),'shifts': [13,18],
                              'golden': 'sim.fixed_ops round_shift + saturate16',
                              'coverage': 'positive/negative ties, normal values, int16 saturation, int36 and int64 endpoints',
                              'result': result},indent=2))
print(result)
