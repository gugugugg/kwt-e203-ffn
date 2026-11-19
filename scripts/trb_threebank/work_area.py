"""Use private native scratch space for this candidate's generated evidence."""
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import time

from native import ROOT, NAME, REPORT, preflight, save
from ffn_delivery_archive import ParallelGzip


def scratch():
    preflight()
    volume = Path("/tmp")
    target = Path(tempfile.mkdtemp(prefix="xpian-threebank-", dir=str(volume)))
    checkpoints = ["complete_soc_sm40_opt_%s_%s_ss_ema2" % (NAME, stage)
                   for stage in ("raw", "hold", "final")]
    paths = [ROOT / tree / NAME for tree in (
        "reports/optimization", "reports/optimization/complete_soc",
        "build/optimization/complete_soc", "constraints")]
    paths.extend(ROOT / tree / tag for tree in ("build/server", "reports/server") for tag in checkpoints)
    paths.extend(ROOT / "reports/optimization/electrical" / tag.replace("complete_soc_sm40_", "")
                 for tag in checkpoints[1:])
    moved = []
    for source in paths:
        assert source.parent.is_dir() and ROOT in source.parent.resolve().parents
        assert not source.is_symlink()
        mirror = target / source.relative_to(ROOT)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            assert source.is_dir()
            shutil.move(str(source), str(mirror))
        else:
            mirror.mkdir()
        source.symlink_to(mirror, target_is_directory=True)
        moved.append(source.relative_to(ROOT).as_posix())
    save(REPORT / "native-scratch.json", dict(root=str(target), candidate=NAME,
         volume_full="/storage2", paths=moved, earlier_source_and_release_unchanged=True))
    print("THREEBANK_SCRATCH", target, flush=True)


def write_archive(archive, files, root):
    """Dereference scratch paths while retaining the project-relative member names."""
    start = time.monotonic()
    files = sorted(files)
    with archive.open("wb") as output:
        compressed = ParallelGzip(output)
        try:
            with tarfile.open(fileobj=compressed, mode="w|", dereference=True) as bundle:
                for path in files:
                    bundle.add(str(path), arcname=path.relative_to(root).as_posix(), recursive=False)
        finally:
            compressed.close()
    save(archive.with_suffix(".metrics.json"), dict(files=len(files), bytes=archive.stat().st_size,
         seconds=time.monotonic()-start, dereferenced_candidate_scratch_paths=True))


if __name__=="__main__":
    scratch()

