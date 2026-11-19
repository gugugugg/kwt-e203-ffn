"""Resolve the four actual phase exceptions and the native mapped observations."""
from pathlib import Path
import json
import re
import shutil

from phase_local import REVIEW, NAME, ARCHIVE


def read(name):
    return json.loads((REVIEW/(name+".json")).read_text())


def write(name,value):
    (REVIEW/(name+".json")).write_text(json.dumps(value,indent=2)+"\n")


def main():
    inv=read("inventory")
    cells=inv["cells"]
    pending=read("phase-review-pending")
    draft=read("corrections-draft")
    assert len(pending)==4 and all(row["kind"]=="net_semantics" for row in pending)
    connection=read("connectivity")
    vendor=(REVIEW/"vendor-functions.v").read_text()
    netlist=(ARCHIVE/"build/server"/("complete_soc_sm40_"+inv["tag"])/"netlist.v").read_text()
    modules={m[1]:m[2] for m in re.finditer(r"(?ms)^module\s+(\w+)\b(.*?)^endmodule",netlist)}

    def literal(cell,pattern):
        body=re.search(r"(?ms)^\s*module\s+"+cells[cell]["ref"]+r"\s*\((.*?)endmodule",vendor)[1]
        assert re.search(pattern,body),(cell,pattern)

    evidence=[]
    for row in pending:
        segment=row["segment"]
        actual=row["drivers"][0]["cell"]
        if segment=="shared_memory/memory/en_BAR":
            assert actual=="shared_memory/U11"
            literal(actual,r"\bnor\s+\w+\s*\(ZN,\s*A1,\s*A2\)")
            assert cells["shared_memory/memory"]["pins"]["en_BAR"].strip()=="n96"
            assert cells["shared_memory/memory/U1069"]["pins"]["I"]=="en_BAR"
            literal("shared_memory/memory/U1069",r"\bnot\s+\w+\s*\(ZN,\s*I\)")
            reason="U11 NOR produces the active-low memory enable. Macro-side U1069 restores the positive physical_accept qualification."
        elif segment=="shared_memory/memory/stream_write_BAR":
            assert actual=="shared_memory/U591"
            for cell,expected in (("U149",{"I":"host_dual","Z":"n803"}),
                                  ("U12",{"I":"n803","ZN":"n201"}),
                                  ("U591",{"I":"n201","Z":"n836"})):
                assert cells["shared_memory/"+cell]["pins"]==expected
                op,pin=("not","ZN") if cell=="U12" else ("buf","Z")
                literal("shared_memory/"+cell,r"\b"+op+r"\s+\w+\s*\("+pin+r",\s*I\)")
            reason="The U149 buffer, U12 inverter and U591 buffer implement !host_dual at the physical stream-write port."
        else:
            assert segment.endswith(("/pc_dfflr/lden_BAR","/icb2mem_dfflr/lden_BAR"))
            for alias in row["aliases"]:
                path=alias["gate"].rsplit("/",1)[0]
                body=modules[cells[path]["ref"]]
                inverter=re.search(r"CLKINV\w+\s+\w+\s*\(\s*\.I\(lden_BAR\),\s*\.ZN\((n\d+)\)",body)
                assert inverter and re.search(r"NAND2\w+\s+\w+\s*\(\s*\.A1\("+inverter[1]+r"\)",body)
                assert "OAI21" in body and "DRNQV" in body
            reason="The physical lden input is complemented before the actual NAND/OAI D mux selects new data. The original E203 dfflr updates on positive lden."
        row=dict(row,physical_inverted=True,reason=reason)
        evidence.append(row)
        for alias in row["aliases"]:
            draft["aliases"].append(dict(rtl=alias["rtl"],gate=alias["gate"],
                                         inverted=True,reason=reason,evidence=row))
    write("resolved-threebank-phases",evidence)
    draft["pending"]=0
    by_rtl={a["rtl"]:a for a in draft["aliases"]}
    suppressed=[]
    for group in read("net-alias-collisions"):
        canonical=[a for a in group["aliases"] if a["rtl"].endswith(("/jtag_TRST","/qout[1]"))]
        assert len(canonical)==1 and not by_rtl.get(canonical[0]["rtl"],{}).get("inverted",False)
        source=canonical[0]["saif"]
        for row in group["aliases"]:
            if row["rtl"]==canonical[0]["rtl"]:
                continue
            assert by_rtl[row["rtl"]]["inverted"]
            other=row["saif"]
            assert (source["T0"],source["T1"],source["TC"])==(other["T1"],other["T0"],other["TC"])
            suppressed.append(row["rtl"])
    draft["suppressed_opposite_phase_aliases"]=sorted(suppressed)
    write("corrections-draft",draft)
    write("phase-review-pending",[])
    macros=read("private-memory-probe-list")
    for macro in macros:
        macro.update(cells[macro["cell"]])
    inv["input_macros"]=[m for m in macros if m["ref"]=="RAMSP1024X16"]
    write("weight-macros",[m for m in macros if m["ref"]=="RAMSP128X16"])
    write("inventory",inv)
    extra=REVIEW/"phase-extra-segments"
    extra.mkdir(exist_ok=True)
    shutil.copyfile(REVIEW/"segments.rpt",extra/"segments.rpt")

    shared=cells["shared_memory"]["pins"]
    soc=cells["soc"]["pins"]
    for port in ("ld_cmd_valid","ld_cmd_ready","wb_ack_valid","wb_ack_ready"):
        assert shared[port].strip()==soc[port].strip()==port
    assert shared["cpu_cmd_valid_BAR"].strip()=="sysmem_icb_cmd_valid"
    assert by_rtl["shared_memory/cpu_cmd_valid"]["inverted"]
    assert cells["shared_memory/result_pending_reg"]["pins"]["Q"].strip()=="wb_ack_valid"
    write("mapped-expressions",dict(variant=NAME,tag=inv["tag"],reviewed=True,
        expressions=dict(cpu_fire="(!dut.shared_memory.cpu_cmd_valid_BAR)&&dut.shared_memory.cpu_cmd_ready",
                         cpu_address="dut.shared_memory.cpu_cmd_addr",
                         cpu_data="dut.shared_memory.cpu_cmd_wdata",cpu_read="dut.shared_memory.cpu_cmd_read",
                         source_fire="dut.ld_cmd_valid&&dut.ld_cmd_ready",
                         result_ack="dut.wb_ack_valid&&dut.wb_ack_ready")))
    print("THREEBANK_PHASE_EXCEPTIONS_RESOLVED",len(evidence),len(suppressed))


if __name__=="__main__":
    main()

