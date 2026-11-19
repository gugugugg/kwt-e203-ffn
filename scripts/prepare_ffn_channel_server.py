from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = []
    for directory in ['rtl', 'third_party/e203_hbirdv2/rtl/e203', 'software/kwt_channel',
                      'build/ffn_ablation/channel_images', 'build/ffn_ablation/channel_vectors']:
        files += [p for p in (ROOT / directory).rglob('*') if p.is_file()]
    files += [ROOT / name for name in ['third_party/e203_hbirdv2/LICENSE', 'build/cpu/e203_cpu_instance.svh',
        'build/ffn_ablation/kwt_cpu_soc.sv', 'build/ffn_ablation/D_combined/firmware_itcm.hex',
        'build/ffn_ablation/D_combined/firmware.elf', 'tb/server/server_ffn_tb.sv', 'scripts/server/run_ffn_channel_vcs.sh']]
    out = ROOT / 'build/server_upload/ffn_channel_20261027.tar.gz'
    with tarfile.open(out, 'w:gz') as bundle:
        for path in sorted(set(files)):
            bundle.add(path, arcname=path.relative_to(ROOT).as_posix())
    print(str(out) + ' bytes=' + str(out.stat().st_size), flush=True)


if __name__ == '__main__':
    main()
