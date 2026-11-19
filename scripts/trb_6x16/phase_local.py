"""Review locally the actual final netlist, same-case SAIF, and native pin segments."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
NAME="ffn_trb_sixteen"
REL=Path("reports/optimization/ffn_trb_6x16")
REPORT=ROOT/REL
ARCHIVE=REPORT/"received/inputs/native-evidence"
REVIEW=ARCHIVE/REL/"activity-mapping/native-review-next"/NAME
sys.path[:0]=[str(ROOT/"scripts"/part) for part in ("sr_transport_next","server","")]


def main():
    import ffn_sr_area as area
    area.ROOT=ARCHIVE
    area.REPORT=ARCHIVE/REL
    area.review_group=lambda _: "next"
    action=sys.argv[1]
    if action=="inspect":
        from sr_area_phase_inventory import inventory
        from sr_area_phase_connectivity import analyze
        from sr_area_phase_prepare import prepare
        from sr_area_phase_review import review
        inventory(NAME)
        analyze(NAME)
        prepare(NAME)
        review(NAME)
    elif action=="assemble":
        from assemble_ffn_sr_area_review import assemble
        assemble(NAME)
    elif action=="verify":
        from review_local import verify_probe
        verify_probe(NAME,REPORT,REVIEW,sys.argv[2])
    else:
        raise ValueError(action)


if __name__=="__main__":
    main()


