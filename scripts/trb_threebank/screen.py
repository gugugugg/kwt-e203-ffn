"""Reproduce the twelve frozen cold tasks with independent source/result owners."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/optimization/ffn_trb_threebank"
spec = importlib.util.spec_from_file_location("twopage", ROOT / "scripts/trb_twopage/screen.py")
base = importlib.util.module_from_spec(spec)
# Dataclasses resolve their defining module while importing the frozen model.
import sys
sys.modules[spec.name] = base
spec.loader.exec_module(base)


class ThreeBankTask(base.StreamingTask):
    def __init__(self, *args):
        super().__init__(*args)
        self.write_ack = None

    def transfer(self, ports):
        previous = self.bus_pending
        self.bus_pending = None
        if previous:
            _, address, word = previous
            self.incoming.append((address, word))
            assert len(self.incoming) <= 2
        if self.write_ack is not None:
            assert self.write_ack == self.cycle - 1
            self.stats["write_ack"] += 1
            self.write_ack = None
            if self.stats["write_ack"] == base.RESULT_COUNT // 2:
                self.marks["final_ack"] = self.cycle

        banks = set()
        cpu_busy = self.cycle in self.cpu_reserved
        setup = self.cpu_setup.get(self.cycle)
        if setup:
            address = (setup["address"] - base.baseline.t.BASE) // 4
            banks.add(base.physical_bank(address))
            if setup["read"]:
                assert self.shared[address] == 1
            else:
                self.shared[address] = setup["data"]

        source = self.next_source()
        if source is not None:
            assert not cpu_busy
            bank = base.physical_bank(source)
            assert bank in (0, 1, 8, 9, 10)
            banks.add(bank)
            self.bus_pending = "read", source, self.shared[source]
            self.read_index += 1
            if source >= base.PARAMETER_BASE:
                tile, offset = divmod(source - base.PARAMETER_BASE, base.PACKET_WORDS)
                if offset == 0:
                    assert self.pages[tile % 2] is None
                    self.pages[tile % 2] = base.Page(tile)

        if self.host_index < len(self.host_order) and self.cycle >= self.host_start:
            addr, data = self.host_order[self.host_index]
            bank = base.physical_bank(addr)
            allowed = ((source is None and previous is None and not cpu_busy) or
                       (source is not None and bank not in banks))
            if allowed:
                assert bank not in banks and addr not in self.out_memory
                banks.add(bank)
                if addr in self.source:
                    assert addr not in self.shared
                    self.stats["host_payload_commits"] += 1
                    self.marks.setdefault("first_host_physical_commit", self.cycle)
                else:
                    self.stats["host_setup_commits"] += 1
                self.shared[addr] = data
                self.host_index += 1
                self.stats["host_dual"] += source is not None
            else:
                self.stats["host_wait_" + ("same_bank" if source is not None else "owner")] += 1

        if self.out_held:
            packet = self.out_held[0]
            bank = base.physical_bank(base.RESULT_BASE + packet[1] // 2)
            assert 4 <= bank <= 7
            if bank not in banks:
                banks.add(bank)
                self.out_held.popleft()
                self.write_shared(packet)
                self.write_ack = self.cycle
            else:
                self.stats["result_shared_bank_wait"] += 1

        if self.out_pending is not None:
            self.out_held.append(self.out_pending)
            self.out_pending = None
        self.prefetch_output(ports)
        self.read_peak = max(self.read_peak, len(self.incoming) + int(source is not None))
        self.output_credit_peak = max(self.output_credit_peak,
                                      len(self.out_held) + int(self.out_pending is not None))
        assert self.read_peak <= 2 and self.output_credit_peak <= 2
        self.stats["shared_bank_accesses_" + str(len(banks))] += 1


def candidate(case, controls, kickoff, host_start, cpu_setup):
    return ThreeBankTask(case, controls, kickoff, host_start, cpu_setup).run()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=int, choices=range(1, 13))
    args = parser.parse_args()
    program, controls, host_start, _ = base.baseline.observe()
    kickoff = next(cmd["accept"] for cmd in program if cmd["bus"] == "cpu"
                   and cmd["address"] == 0x48 and not cmd["read"])
    setup = [cmd for cmd in program if cmd["bus"] == "shared_cpu" and cmd["accept"] < kickoff]
    controls = controls + [(base.baseline.t.READY_WORD, 1)]
    if args.case is not None:
        row = candidate(args.case - 1, controls, kickoff, host_start, setup)
        print(json.dumps(row, indent=2))
        return
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(candidate, case, controls, kickoff, host_start, setup) for case in range(12)]
        rows = [job.result() for job in jobs]
    for row in rows:
        print(row["case"], row["complete"], row["cold_cycles"], row["counters"]["shared_bank_accesses_3"])
        assert row["complete"] and row["counters"]["write_ack"] == 12672
    cycles = sum(row["cold_cycles"] for row in rows)
    evidence = dict(cold_cycles_total=cycles, throughput=12 * base.CLOCK / cycles,
                    target_cycles=base.CYCLE_TARGET, passes_model=cycles <= base.CYCLE_TARGET,
                    frozen_twopage_cycles_total=348660, rows=rows)
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "screen.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("Aggregate:", cycles, evidence["throughput"], evidence["passes_model"])


if __name__ == "__main__":
    main()

