"""Close the observed 31-stage reference cut's capacitance violations."""
from slice import ROOT, REPORT, NATIVE, LIBS, TIMING, job, preflight, save, ship
import re


def main():
    preflight()
    previous=NATIVE/"operand/hold"
    out=NATIVE/"operand/hold-repaired"
    out.mkdir(exist_ok=True)
    prefix="set out {%s}\n" % out.relative_to(ROOT).as_posix()
    tcl=(ROOT/"scripts/server/repair_optimization_electrical.tcl").read_text()
    tcl=tcl.replace("reports/server/${previous}/pt/constraints.rpt",
                    (previous/"constraints.rpt").relative_to(ROOT).as_posix())
    tcl=tcl.replace("set split_at [string first max_transition $violations]",
                    "set split_at [string first max_transition $violations]\n"
                    "if {$split_at == -1} {set split_at [string length $violations]}")
    dc=out/"repair.tcl"
    dc.write_text(prefix+LIBS+"""
set_host_options -max_cores 4
set_app_var target_library [list $db]
set_app_var link_library [list * $db]
set env(XPIAN_DRC_FROM) %s
read_ddc $env(XPIAN_DRC_FROM)
current_design study_operand
link
""" % (previous/"design.ddc").relative_to(ROOT).as_posix()+tcl+"""
redirect $out/area.rpt {report_area -hierarchy}
write -format verilog -hierarchy -output $out/netlist.v
write -format ddc -hierarchy -output $out/design.ddc
exit
""")
    (out/"slice.sdc").write_bytes((previous/"slice.sdc").read_bytes())
    pt=out/"timing.tcl"
    pt.write_text(prefix+LIBS+TIMING.replace("study_column","study_operand"))
    job(["dc_shell","-f",dc],out/"dc.log")
    job(["pt_shell","-f",pt],out/"pt.log")
    area = float(re.search(r"Total cell area:\s+([\d.]+)",(out/"area.rpt").read_text())[1])
    log = (out/"pt.log").read_text()
    slack={kind:float(re.search(r"STUDY_SLACK_"+kind+r"=([-+\d.eE]+)",log)[1])
           for kind in ("max","min")}
    reports=("constraints.rpt","clock_gating_setup.rpt","clock_gating_hold.rpt")
    violations={f:sum("VIOLATED" in l for l in (out/f).read_text().splitlines()) for f in reports}
    save(out/"result.json",dict(area_um2=area,slack_ns=slack,violations=violations))
    ship(REPORT,"operand-repair",list(out.iterdir()))


if __name__=="__main__":
    main()
