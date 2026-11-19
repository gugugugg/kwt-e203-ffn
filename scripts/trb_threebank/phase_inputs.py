"""Collect this final's mapped nets, actual cell functions, and SAIF sources."""
from native import ROOT, NAME, REPORT, OUT, preflight, read, save
import native_activity
import ffn_delivery_archive
from work_area import write_archive

ffn_delivery_archive.write_archive=write_archive


def extend_inventory(name, original, folder):
    summary=original(name)
    inv=read(folder/"inventory.json")
    query=folder/"query-targets.json"
    targets=read(query)
    seen={(row["kind"],row["name"]) for row in targets}

    def add(kind,signal):
        key=kind,signal
        if key not in seen:
            seen.add(key)
            targets.append(dict(kind=kind,name=signal))

    for row in inv["mappings"]:
        rtl=row["rtl"]
        if not row["cell"] and (
            "/accelerator/core/" in rtl or
            "/accelerator/controller/core/" in rtl or
            any(port in rtl for port in ("wb_valid","wb_ready","wb_ack","wb_addr","wb_data"))):
            add("net",row["gate"])
    macros=[]
    for path,cell in inv["cells"].items():
        ref=cell["ref"]
        if "/core/" not in path or ref not in ("RAMSP1024X16","RAMSP128X16"):
            continue
        macros.append(dict(cell=path,reference=ref))
        for pin in ("CLK","CEN","GWEN"):
            add("pin",path+"/"+pin)
        for stem,bits in (("Q",16),("D",16),("WEN",16),("A",7 if ref=="RAMSP128X16" else 10)):
            if "'" not in cell["pins"].get(stem,"'"):
                for bit in range(bits):
                    add("pin",path+"/"+stem+"[%d]"%bit)
    save(query,targets)
    save(folder/"private-memory-probe-list.json",macros)
    summary.update(query_targets=len(targets),private_two_page_and_io_macros=len(macros))
    assert sum(m["reference"]=="RAMSP128X16" for m in macros)==16
    assert sum(m["reference"]=="RAMSP1024X16" for m in macros)==8
    save(folder/"inventory-summary.json",summary)
    return summary


def main():
    preflight()
    _,group=native_activity.bind(NAME)
    import sr_area_phase_inventory as inventory
    original=inventory.inventory
    inventory.inventory=lambda name:extend_inventory(name,original,group/name)
    native_activity.collect(NAME)


if __name__=="__main__":
    main()

