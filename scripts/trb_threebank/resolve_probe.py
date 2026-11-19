"""Keep the proven physical producer on the four aliased probe segments."""
import json
import shutil

from phase_local import REPORT, REVIEW, NAME
from resolve_phase import read, write


def main():
    evidence=REPORT/"phase-verdict.json"
    verdict=json.loads(evidence.read_text())
    assert verdict["attempt"]=="probe-attempt-01" and not verdict["passed"]
    conn=read("connectivity")
    inv=read("inventory")
    draft=read("corrections-draft")
    expectations=read("phase-expectations")["nets"]
    segments={}
    for row in verdict["mismatches"]:
        net=row["net"]
        segments[conn["representatives"].get(net,net)]=expectations[net]["sources"]
    assert len(segments)==4
    backup=REVIEW/"probe01-phase-recovery"
    backup.mkdir(exist_ok=True)
    shutil.copyfile(evidence,backup/"phase-verdict.json")
    for name in ("phase-expectations.json","corrections-draft.json"):
        shutil.copyfile(REVIEW/name,backup/name)
    opposite=set(draft["suppressed_opposite_phase_aliases"])
    duplicate=set(draft.get("deduplicated_positive_aliases",[]))
    result=[]
    for segment,rows in segments.items():
        driver,=conn["drivers"][segment]
        pins={k:v.strip() for k,v in inv["cells"][driver["cell"]]["pins"].items()}
        ref=driver["ref"]
        if ref=="NAND2V2_12TR40" and pins["ZN"]=="cmt_dpc_ena_BAR":
            producer="/step_req_dfflr/dnxt[0]"
            reason="The positive step-request D input is the exact NAND output; the debug-entry enable aliases carry its inverse."
        elif ref=="CLKMUX2V12_12TR40" and pins["Z"]=="io_sync_reset":
            producer="/aonrst_catch/io_sync_reset"
            reason="The clock mux drives active-high synchronized reset; the lclkgen active-low reset aliases carry its inverse."
        elif ref=="CLKBUFV6_12TR40" and pins["Z"]=="o_dat[55]":
            producer="/u_byp_icb_cmd_buf/o_dat[55]"
            reason="The positive ICB read direction on bit 55 drives the physical active-low RAM write qualification."
        elif ref=="AND3V0_12TR40" and pins["Z"]=="longp_wbck_o_valid":
            producer="/u_e203_exu_longpwbck/longp_wbck_o_valid"
            reason="The writeback arbiter prioritizes the long-pipeline valid signal. Its actual AND output is the inverse of ALU ready."
        else:
            raise RuntimeError((segment,ref,pins))
        chosen,=[row for row in rows if row["rtl"].endswith(producer)]
        assert not chosen["inverted"]
        for row in rows:
            if row["rtl"]==chosen["rtl"]:
                continue
            stats=row["raw"]
            known=chosen["raw"]
            if row["inverted"]:
                assert (stats["T0"],stats["T1"],stats["TC"])==(known["T1"],known["T0"],known["TC"])
                opposite.add(row["rtl"])
            else:
                assert (stats["T0"],stats["T1"],stats["TC"])==(known["T0"],known["T1"],known["TC"])
                duplicate.add(row["rtl"])
        result.append(dict(segment=segment,driver=driver,pins=pins,kept=chosen["rtl"],reason=reason))
    draft["suppressed_opposite_phase_aliases"]=sorted(opposite)
    draft["deduplicated_positive_aliases"]=sorted(duplicate)
    write("probe02-physical-producers",result)
    write("corrections-draft",draft)
    print("THREEBANK_PROBE02_ACTUAL_PRODUCERS",len(result),len(opposite),len(duplicate))


if __name__=="__main__":
    main()

