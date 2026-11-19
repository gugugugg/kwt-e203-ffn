"""Exhaust the abstract issue scheduler for the 16 quantizer tap ages."""
from collections import deque
import json
from pathlib import Path

from build import ROOT

# A full unit issues k=0..63 on each of two consecutive sides (128 tokens).
# A tail unit issues k=0..63 on one side (64 tokens). The actual choose
# logic restricts start time; allowing either kind on every idle edge is
# a superset. Only completed unit bodies may take this idle transition.
# Asynchronous reset aborts an active unit; first post-reset issue still
# requires 256 input words plus one 1064-word page at <=2 returned words
# per edge, which clears all 32 in-flight tap ages before new issue.
TAPS = sum(1 << age for age in range(0, 31, 2))
KEEP = (1 << 31) - 1


def successors(kind, next_index):
    if kind == 0:
        return ((0, 0, False), (64, 1, False), (128, 1, False))
    k = next_index if kind == 64 else next_index // 2
    next_state = (0, 0) if next_index + 1 == kind else (kind, next_index + 1)
    return (next_state + (k == 63,),)


def main():
    initial = (0, 0, 0)
    seen = {initial}
    queue = deque([initial])
    edges = 0
    while queue:
        kind, index, history = queue.popleft()
        selected = history & TAPS
        if selected & (selected - 1):
            raise ValueError((kind, index, history))
        for next_kind, next_index, last in successors(kind, index):
            updated = ((history << 1) & KEEP) | last
            state = next_kind, next_index, updated
            if state not in seen:
                seen.add(state)
                queue.append(state)
            edges += 1
    evidence = {"passed": True, "reachable_states": len(seen), "transitions": edges,
                "ages": list(range(2, 33, 2)), "idle_starts_overapproximated": True,
                "full_unit": 128, "tail_unit": 64}
    path = ROOT / "reports/optimization/ffn_trb_pair_area_power/local/QM/emit-onehot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()

