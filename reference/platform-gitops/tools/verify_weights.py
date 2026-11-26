#!/usr/bin/env python3
"""Verify one weights PVC against the catalogue before any model may start from it. Stdlib only.

    python3 verify_weights.py --root /weights --manifest-sha256 <64 hex>

The tracked transfer puts MANIFEST.sha256 at the PVC root, in `sha256sum` format ("<hex>  <relative path>").
  1. sha256(MANIFEST.sha256) must equal the catalogue's weights.manifest_sha256 (so the manifest is the reviewed one);
  2. every listed file must exist inside the root (no absolute paths, no '..') and hash to its listed value;
  3. no file may exist that the manifest does not list (except MANIFEST.sha256 and the markers);
  4. only then is the marker .verified-<manifest_sha256> written; the NIMService init container requires it.
Never modifies the weights. Exit 0 verified, 1 mismatch, 2 usage / unreadable manifest.
"""
from __future__ import annotations
import argparse, hashlib, re, sys
from pathlib import Path, PurePosixPath

LINE = re.compile(r"^([0-9a-f]{64}) [ *](.+)$")


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(root: Path, expected: str) -> list[str]:
    manifest = root / "MANIFEST.sha256"
    if not manifest.is_file():
        return [f"{manifest} missing"]
    got = file_sha256(manifest)
    if got != expected:
        return [f"MANIFEST.sha256 is {got}, catalogue says {expected}"]
    problems, n, listed = [], 0, set()
    for i, line in enumerate(manifest.read_text().splitlines(), 1):
        if not line.strip():
            continue
        m = LINE.match(line)
        if not m:
            problems.append(f"line {i}: not '<sha256>  <path>'"); continue
        rel = PurePosixPath(m.group(2))
        if rel.is_absolute() or ".." in rel.parts:
            problems.append(f"line {i}: path {rel} escapes the weights root"); continue
        listed.add(rel.as_posix())
        p = root / rel
        if not p.is_file():
            problems.append(f"{rel}: missing"); continue
        if file_sha256(p) != m.group(1):
            problems.append(f"{rel}: sha256 mismatch")
        n += 1
    if n == 0 and not problems:
        problems.append("manifest lists no files")
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and rel != "MANIFEST.sha256" and not rel.startswith(".verified-") and rel not in listed:
            problems.append(f"{rel}: present but not in the manifest (an unreviewed file would be served)")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--manifest-sha256", required=True)
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{64}", a.manifest_sha256):
        print("--manifest-sha256 must be 64 lower-case hex", file=sys.stderr)
        return 2
    problems = verify(a.root, a.manifest_sha256)
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        return 1
    (a.root / f".verified-{a.manifest_sha256}").write_text("verified\n")
    print(f"verified: marker .verified-{a.manifest_sha256} written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
