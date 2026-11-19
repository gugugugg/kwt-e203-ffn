"""Read only the two new actual pending functions and their driver cones."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];BASE=ROOT/'reports/optimization/ffn_c_final_energy/activity-mapping/native-review-first'

def model(text,ref):
    start=text.index('module '+ref+' ');return text[start:text.index('endmodule',start)].split('specify')[0]

def main():
    text=(BASE/'ffn_cfe_SS/vendor-functions.v').read_text();print('SS_LITERAL_MODEL',model(text,'LAHQNV0_12TR40'))
    inputs=json.loads((BASE/'ffn_cfe_SS/cell-inverted-review-inputs.json').read_text());print('SS_INPUT16',json.dumps([v for v in inputs if v['rtl'].endswith('/jp_input_return[16]')]))
    own=BASE/'ffn_cfe_O1';inv=json.loads((own/'inventory.json').read_text());conn=json.loads((own/'connectivity.json').read_text());cell='soc/u_e203_subsys_main/u_e203_cpu_top/u_e203_cpu/u_e203_core/u_e203_exu/u_e203_exu_alu/U211'
    print('O1_BUF',json.dumps(inv['cells'][cell]));wire=conn['pins'][cell+'/I'];rep=conn['representatives'].get(wire,wire);drivers=conn['drivers'].get(rep,[])
    print('INPUT_WIRE',wire,'DRIVERS',json.dumps(drivers),'ALIASES',json.dumps(conn['aliases'].get(rep)))
    for driver in drivers:print('SOURCE_CELL',driver['cell'],json.dumps(inv['cells'][driver['cell']]))
    f=ROOT/'build/optimization/complete_soc/ffn_cfe_O1/synthesis_files.f';print('RTLFILES',json.dumps([x for x in f.read_text().splitlines() if 'exu_alu' in x]))

if __name__=='__main__':main()
