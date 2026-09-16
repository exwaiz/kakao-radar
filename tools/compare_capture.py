"""Compare an explicitly bounded capture against independently verified message text."""
import argparse
import json
from collections import deque
from pathlib import Path


def read_jsonl(path):
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at line {number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Expected object at line {number}")
        rows.append(row)
    return rows


def compare(captured, truth, tolerance_ms=5000):
    edges = []
    for expected in truth:
        if not isinstance(expected.get("text"), str):
            raise ValueError("Every ground-truth row must contain text")
        choices = []
        for candidate in range(len(captured)):
            actual = captured[candidate]
            if actual.get("text") != expected["text"]:
                continue
            et, at = expected.get("source_time"), actual.get("source_time")
            if et is not None and at is not None:
                distance = abs(et - at)
                if distance > tolerance_ms:
                    continue
            else:
                distance = float("inf")
            choices.append((distance, candidate))
        edges.append([candidate for _, candidate in sorted(choices)])
    # Maximum one-to-one matching avoids nearest-first undercounting repeated text.
    owner, assignment = {}, {}
    for start in range(len(truth)):
        queue, visited, parents = deque([start]), {start}, {}
        free = None
        while queue and free is None:
            expected_index = queue.popleft()
            for candidate in edges[expected_index]:
                if candidate in parents:
                    continue
                parents[candidate] = expected_index
                if candidate not in owner:
                    free = candidate
                    break
                previous_owner = owner[candidate]
                if previous_owner not in visited:
                    visited.add(previous_owner)
                    queue.append(previous_owner)
        while free is not None:
            expected_index = parents[free]
            old = assignment.get(expected_index)
            owner[free], assignment[expected_index] = expected_index, free
            free = old
    matched = len(assignment)
    missing = [i + 1 for i in range(len(truth)) if i not in assignment]
    return {"ground_truth_count": len(truth), "capture_count": len(captured),
            "matched": matched, "sample_recall": matched / len(truth) if truth else None,
            "missing_ground_truth_rows": missing, "unmatched_capture_count": len(captured) - matched,
            "note": "Unmatched capture rows are not necessarily duplicates; this is sample recall only."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture")
    parser.add_argument("ground_truth")
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--from-ms", type=int, required=True)
    parser.add_argument("--to-ms", type=int, required=True)
    args = parser.parse_args()
    if args.from_ms >= args.to_ms:
        parser.error("--from-ms must precede --to-ms")
    captured = [r for r in read_jsonl(args.capture)
                if r.get("type") == "message" and r.get("room_id") == args.room_id
                and args.from_ms <= (r.get("source_time") or r.get("observed_at", 0)) < args.to_ms]
    truth = read_jsonl(args.ground_truth)
    if any(r.get("source_time") is not None and not args.from_ms <= r["source_time"] < args.to_ms for r in truth):
        parser.error("Ground truth contains timestamps outside the selected interval")
    if not truth:
        parser.error("Ground truth must not be empty")
    print(json.dumps(compare(captured, truth), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
