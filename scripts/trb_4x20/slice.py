"""Map and time the paired, same-library column cuts on the native host."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import re

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "trb_threebank"))
from native import ROOT, job, preflight, save
from native_delivery import ship
import native_delivery
from work_area import write_archive

REPORT = ROOT / "reports/optimization/ffn_trb_4x20_study"
NATIVE = REPORT / "native"
native_delivery.write_archive = write_archive

LIBS = '''
set db [exec find build/server/technology -name scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db]
set macro build/server/technology/ram_db/RAMSP128X16_ss_0p99v_0p99v_125c.db
'''
CONSTRAINTS = '''
create_clock -name clk -period 6.666666 [get_ports clk]
set_clock_transition 0.1 [all_clocks]
set inputs [remove_from_collection [all_inputs] [get_ports clk]]
set_input_transition 0.1 $inputs
set_input_delay -clock clk -max 0.7 $inputs
set_input_delay -clock clk -min 0.7 $inputs
set_output_delay -clock clk 0 [all_outputs]
set_load 0.002856 [all_outputs]
set_operating_conditions -analysis_type on_chip_variation ss_v0p99_125c
'''
SYNTH = '''
set_host_options -max_cores 4
set_app_var target_library [list $db]
set_app_var synthetic_library dw_foundation.sldb
set_app_var link_library [concat [list *] $target_library $macro dw_foundation.sldb]
define_design_lib WORK -path $out/work
analyze -format sverilog $out/column.sv
elaborate study_column
current_design study_column
link
source $out/slice.sdc
set_fix_hold [get_clocks clk]
set memories [get_cells -quiet -hierarchical -filter {ref_name =~ RAMSP*}]
if {[sizeof_collection $memories] != 0} {set_dont_touch $memories}
compile_ultra -no_autoungroup
change_names -rules verilog -hierarchy
redirect $out/area.rpt {report_area -hierarchy}
redirect $out/resources.rpt {report_resources -hierarchy}
redirect $out/cells.rpt {report_cell [get_cells -hierarchical *]}
redirect $out/dc_constraints.rpt {report_constraint -all_violators}
write -format verilog -hierarchy -output $out/netlist.v
write -format ddc -hierarchy -output $out/design.ddc
puts STUDY_DC_DONE
exit
'''
TIMING = '''
set_host_options -max_cores 8
set link_path [list * $db $macro]
read_verilog $out/netlist.v
current_design study_column
link_design
source $out/slice.sdc
update_timing
foreach kind {max min} {
    redirect $out/timing_$kind.rpt {report_timing -delay_type $kind -max_paths 10 -slack_lesser_than 1000000 -significant_digits 9 -path_type full_clock_expanded}
    set paths [get_timing_paths -delay_type $kind -max_paths 1 -slack_lesser_than 1000000]
    puts "STUDY_SLACK_$kind=[get_attribute $paths slack]"
}
redirect $out/constraints.rpt {report_constraint -all_violators -significant_digits 9}
redirect $out/clock_gating_setup.rpt {report_constraint -clock_gating_setup -verbose -significant_digits 9}
redirect $out/clock_gating_hold.rpt {report_constraint -clock_gating_hold -verbose -significant_digits 9}
puts STUDY_PT_DONE
exit
'''


def run(gated, operand=False):
    mode = "icg" if gated else "hold"
    out = NATIVE / ("operand" if operand else "slice") / mode
    out.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("operand.sv" if operand else "column.sv").read_text()
    top = "study_operand" if operand else "study_column"
    if operand:
        source = source.replace("STUDY_DEPTH", "39" if gated else "31")
    (out/"column.sv").write_text(source.replace("STUDY_GATED",str(int(gated))))
    (out/"slice.sdc").write_text(CONSTRAINTS)
    prefix = "set out {%s}\n" % out.relative_to(ROOT).as_posix()
    dc = out/"synthesize.tcl"
    pt = out/"timing.tcl"
    dc.write_text(prefix+LIBS+SYNTH.replace("study_column",top))
    pt.write_text(prefix+LIBS+TIMING.replace("study_column",top))
    if not (out/"netlist.v").is_file():
        job(["dc_shell","-f",dc],out/"dc.log")
    job(["pt_shell","-f",pt],out/"pt.log")
    area = (out/"area.rpt").read_text()
    log = (out/"pt.log").read_text()
    assert "STUDY_PT_DONE" in log and "STUDY_DC_DONE" in (out/"dc.log").read_text()
    total = float(re.search(r"Total cell area:\s+([\d.]+)",area)[1])
    slack = {kind:float(re.search(r"STUDY_SLACK_"+kind+r"=([-+\d.eE]+)",log)[1])
             for kind in ("max","min")}
    constraints = ("constraints.rpt","clock_gating_setup.rpt","clock_gating_hold.rpt")
    violations = {f:sum("VIOLATED" in l for l in (out/f).read_text().splitlines()) for f in constraints}
    return dict(mode=mode,area_um2=total,slack_ns=slack,violations=violations)


def main():
    preflight()
    with ThreadPoolExecutor(max_workers=2) as pool:
        operand = "operand" in sys.argv
        hold, icg = pool.map(lambda gated: run(gated, operand), [False,True])
    mode = "operand" if operand else "slice"
    path = NATIVE/mode/"result.json"
    save(path,dict(hold=hold,icg=icg,recovered_um2=hold["area_um2"]-icg["area_um2"]))
    files = [p for p in path.parent.rglob("*") if p.is_file() and "work" not in p.parts]
    ship(REPORT,mode,files)


if __name__ == "__main__":
    main()
