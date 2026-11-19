"""Generate the first AH activity review from the returned actual inputs."""
from pathlib import Path
import json
import shutil
import sys

from prepare import ROOT, REPORT

NAME = 'ffn_sr_ah'
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'scripts/server')]
import ffn_sr_area as area

SOURCE = REPORT/'received/eco3-input/native-evidence'
area.ROOT = SOURCE
area.REPORT = SOURCE/REPORT.relative_to(ROOT)
area.review_group = lambda _: 'branch'
from sr_area_phase_inventory import inventory
from sr_area_phase_connectivity import analyze
from sr_area_phase_prepare import prepare
from sr_area_phase_review import review


def main():
    inventory(NAME)
    analyze(NAME)
    prepare(NAME)
    review(NAME)


if __name__=='__main__':
    main()
