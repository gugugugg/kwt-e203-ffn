"""Collect the missing macro path groups on the existing final checkpoint."""
import os
import re
import shutil

from native import ROOT, REPORT, OUT, PATHS, preflight, read, save, job


def main():
    preflight()
    screen_file = REPORT / "final-screen.json"
    screen = read(screen_file)
    old = screen["checks"]["pr1_paths"]["groups"]
    assert old["quant_to_scratch"]["targets"] == old["scratch_to_fifo"]["sources"] == 0
    folder = REPORT / "final-path-diagnostics"
    folder.mkdir()
    shutil.copyfile(screen_file, folder / "original-final-screen.json")
    header = (OUT / "eda/time.tcl").read_text().split("update_timing\n", 1)[0]
    groups = PATHS[PATHS.index("set writer"):PATHS.index('puts "XPIAN_PR1_ASSESSMENT_DONE')]
    script = folder / "assess_existing_final.tcl"
    script.write_text(header + "update_timing\nset report {" + folder.relative_to(ROOT).as_posix() +
                      "}\n" + groups + '\nputs "XPIAN_WIDE_PATHS_DONE"\nexit\n')
    log = folder / "pt.log"
    job(["pt_shell", "-f", script], log, dict(os.environ, XPIAN_CORNER="ss", XPIAN_TAG=screen["tag"]))
    assert "XPIAN_WIDE_PATHS_DONE" in log.read_text()
    text = (folder / "pr1_paths.rpt").read_text()
    paths = {}
    for label, sources, targets, block in re.findall(
            r"(?ms)^PR1_PATH_GROUP (\w+) (\d+) (\d+)\n(.*?)(?=^PR1_PATH_GROUP|\Z)", text):
        sections = block.split("PR1_PATH_DELAY min")
        paths[label] = dict(sources=int(sources), targets=int(targets),
                            max_paths=sections[0].count("slack ("),
                            min_paths=sections[-1].count("slack (") if len(sections) == 2 else 0)
    screen["checks"]["pr1_paths"] = dict(violations=text.count("(VIOLATED)"), groups=paths)
    checks = screen["checks"]
    screen["timing_passed"] = (len(paths) == 5 and all(g["max_paths"] and g["min_paths"] for g in paths.values()) and
                               checks["setup_slack_ns"] >= 0 and checks["hold_slack_ns"] >= 0 and
                               all(checks[k]["violations"] == 0 for k in (
                                   "clock_gating_setup", "clock_gating_hold", "constraints", "pr1_paths")))
    screen["diagnostics_report"] = (folder / "pr1_paths.rpt").relative_to(ROOT).as_posix()
    save(screen_file, screen)
    print("WIDE_FINAL_ASSESSED", screen["timing_passed"], screen["area_passed"], flush=True)


if __name__ == "__main__":
    main()
