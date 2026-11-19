"""Read the actual Q4 final archive with the shared phase-analysis routines."""
import sys
from prepare import ROOT, REPORT, VARIANT

SOURCE = REPORT/'received/q4-input/native-evidence'
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'scripts/server')]
import ffn_sr_area as area
area.ROOT = SOURCE
area.REPORT = SOURCE/REPORT.relative_to(ROOT)
area.review_group=lambda _: 'q4'
from sr_area_phase_inventory import inventory
from sr_area_phase_connectivity import analyze
from sr_area_phase_prepare import prepare
from sr_area_phase_review import review
from assemble_ffn_sr_area_review import assemble


def main():
    inventory(VARIANT)
    analyze(VARIANT)
    prepare(VARIANT)
    review(VARIANT)
    assemble(VARIANT)


if __name__=='__main__':
    main()
