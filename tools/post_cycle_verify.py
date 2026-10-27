#!/usr/bin/env python3
"""Post-power-cycle NVDM verification.

Run this AFTER:
  1. NCOPTSET markers have been sent (via verify_coefset.py or probe script)
  2. Headphones powered OFF (5s hold) then back ON
  3. Bluetooth reconnected

Compares NVDM optimizer_coeff against expected marker pattern.
"""
from __future__ import annotations

import hashlib
import struct
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from xm4_optimizer.transport.rfcomm_socket import create_rfcomm_socket
from xm4_optimizer.transport.protocol_race import RacePacket, RACE_HEADER_SIZE
from xm4_optimizer.nvdm.parser import parse_nvdm_image

RACE_CHANNEL = 21
TOTAL_PEBS = 128
PAGES_PER_PEB = 16
PAGE_SIZE = 256
PEB_SIZE = PAGES_PER_PEB * PAGE_SIZE
MARKER_BASE = 0xDEAD0000
IDENTITY = [0x10000000, 0, 0, 0, 0, 0x10000000, 0, 0, 0, 0]

LABELS = ["L:b0", "L:b1", "L:b2", "L:a1", "L:a2",
          "R:b0", "R:b1", "R:b2", "R:a1", "R:a2"]


def dump_nvdm(bd_addr: str, label: str, out_dir: Path) -> bytes:
    print(f"\n[{label}] NVDM dump başlıyor...")
    sock = create_rfcomm_socket(bd_addr, RACE_CHANNEL, timeout_s=10.0)
    buf = bytearray()
    t0 = time.time()
    try:
        for peb in range(TOTAL_PEBS):
            batch = bytearray()
            for pg in range(PAGES_PER_PEB):
                addr = peb * PEB_SIZE + pg * PAGE_SIZE
                payload = struct.pack("<BBI", 1, 1, addr)
                batch.extend(struct.pack("<BBHH", 0x05, 0x5A, 2 + len(payload), 0x0403) + payload)
            sock.sendall(batch)
            resp = bytearray()
            expected = PAGES_PER_PEB * 270
            while len(resp) < expected:
                chunk = sock.recv(expected - len(resp))
                if not chunk:
                    raise ConnectionError("RFCOMM closed")
                resp.extend(chunk)
            for pg in range(PAGES_PER_PEB):
                frame = resp[pg * 270:(pg + 1) * 270]
                rc = frame[6]
                if rc != 0:
                    raise RuntimeError(f"PAGE_READ error PEB {peb} page {pg}: rc=0x{rc:02X}")
                buf.extend(frame[14:270])
            if (peb + 1) % 32 == 0:
                elapsed = time.time() - t0
                print(f"  [{label}] {peb+1}/{TOTAL_PEBS} PEB ({len(buf)//1024} KB, {elapsed:.1f}s)")
    finally:
        sock.close()
    elapsed = time.time() - t0
    sha = hashlib.sha256(buf).hexdigest()[:16]
    print(f"  [{label}] Tamamlandı: {len(buf)} byte, {elapsed:.1f}s, sha256={sha}...")
    out_path = out_dir / f"nvdm_{label}.bin"
    out_path.write_bytes(bytes(buf))
    return bytes(buf)


def extract_optimizer_coeff(nvdm_bytes: bytes) -> tuple[bytes | None, list[int]]:
    partition = parse_nvdm_image(nvdm_bytes)
    raw = partition.get_value("config", "optimizer_coeff")
    if raw is None:
        return None, []
    words = [struct.unpack(">I", raw[i:i+4])[0] for i in range(0, len(raw), 4) if i + 4 <= len(raw)]
    return raw, words


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mac", default=None)
    parser.add_argument("--out", type=Path, default=Path("verify_coefset_dumps"))
    args = parser.parse_args()

    bd_addr = args.mac
    if bd_addr is None:
        from tools.backup_nvdm import find_connected_xm4_mac
        bd_addr = find_connected_xm4_mac()
        if bd_addr is None:
            print("Kulaklık bulunamadı.")
            return 1
    print(f"Cihaz: {bd_addr}")
    args.out.mkdir(parents=True, exist_ok=True)

    markers = [MARKER_BASE + i for i in range(10)]

    post_bytes = dump_nvdm(bd_addr, "post_cycle", args.out)
    post_raw, post_words = extract_optimizer_coeff(post_bytes)
    if post_raw is None:
        print("HATA: config/optimizer_coeff bulunamadı!")
        return 1

    print(f"\n{'=' * 60}")
    print("POST-CYCLE optimizer_coeff:")
    for i, w in enumerate(post_words):
        lbl = LABELS[i] if i < len(LABELS) else f"[{i}]"
        is_marker = (w & 0xFFFF0000) == MARKER_BASE
        tag = " ← DEAD MARKER" if is_marker else ""
        print(f"  [{i}] {lbl:5s} = 0x{w:08X}{tag}")

    print(f"\n{'=' * 60}")
    marker_count = sum(1 for w in post_words if (w & 0xFFFF0000) == MARKER_BASE)

    if post_words == markers:
        print("*** KANITLI: NCOPTSET → RAM → NVDM pipeline ÇALIŞIYOR ***")
        print(f"Tüm 10 marker eşleşti: {[f'0x{v:08X}' for v in post_words]}")
        return 0
    elif marker_count > 0:
        print(f"KISMEN KANITLI: {marker_count}/10 marker bulundu")
        for i in range(len(post_words)):
            expected = markers[i] if i < len(markers) else "?"
            actual = post_words[i]
            match = "✓" if actual == expected else "✗"
            print(f"  [{i}] beklenen=0x{expected:08X} gerçek=0x{actual:08X} {match}")
        return 0
    elif post_words == IDENTITY:
        print("BAŞARISIZ: NVDM hâlâ identity — NCOPTSET RAM'e yazmadı veya power cycle save tetiklenmedi")
        return 2
    else:
        print("BELİRSİZ: NVDM değişti ama marker deseni değil")
        print(f"Raw hex: {post_raw.hex()}")
        for i in range(len(post_words)):
            if i < len(IDENTITY) and post_words[i] != IDENTITY[i]:
                print(f"  [{i}] identity=0x{IDENTITY[i]:08X} → 0x{post_words[i]:08X}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
