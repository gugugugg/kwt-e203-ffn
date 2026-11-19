"""Convert one official WAV input into an MGPR task with a float reference."""
import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.kwt_reference import KWTReference
from convert import convert, scale_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path, nargs="?", help="Speech Commands V2 WAV")
    parser.add_argument("--layer", required=True, type=int, choices=range(12))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--silence", action="store_true")
    args = parser.parse_args()
    if (args.wav is None) == (not args.silence):
        parser.error("Supply a WAV or --silence")
    model = KWTReference()
    try:
        waveform = model.load_audio({"synthetic_silence": args.silence,
                                     "relative_path": args.wav.resolve() if args.wav else ""})
        inputs, expected = model.infer_ffn_reference(waveform)
    finally:
        model.close()
    args.out.mkdir(parents=True, exist_ok=True)
    with np.load(ROOT / "models/kwt1_float32/parameters_float32.npz", allow_pickle=False) as weights:
        prefix = "encoder.%02d.ffn.fc1." % args.layer
        with TemporaryDirectory(dir=str(args.out)) as scratch:
            path = Path(scratch) / "operands.npz"
            np.savez(path, input=inputs[args.layer], weight=weights[prefix+"kernel"], bias=weights[prefix+"bias"])
            convert(path, args.out, args.layer)
    target = expected[args.layer].astype(np.float64)
    np.save(args.out / "float_reference.npy", target)
    actual = np.load(args.out / "output_decoded.npy")
    nrmse = np.sqrt(np.mean((actual-target)**2)) / max(np.sqrt(np.mean(target**2)), 1e-8)
    print("layer=%d words=%d outputs=%d NRMSE=%.9f%%" %
          (args.layer, int((args.out/"count.hex").read_text(),16), actual.size, 100*nrmse))


if __name__ == "__main__":
    main()
