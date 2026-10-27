#!/usr/bin/env python3
"""NCOPTSET verification via NVDM flash readback.

Proves whether AT+NCOPTTOOL=NCOPTSET actually writes to the optimizer
coefficient RAM buffer by comparing NVDM dumps before and after a
power cycle.

Flow:
  1. Baseline NVDM backup → parse config/optimizer_coeff
  2. Send NCOPTSET with unique marker values via RACE relay mode
  3. Wait for power cycle (user turns headphones off/on)
  4. Post NVDM backup → parse config/optimizer_coeff
  5. Compare: if marker values appear → PROVEN
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from xm4_optimizer.transport.rfcomm_socket import create_rfcomm_socket
from xm4_optimizer.transport.protocol_race import (
    RacePacket, RaceHead, RaceHeaderType, RaceOpcode,
    AtciTunnelRequest, RACE_HEADER_SIZE,
)
from xm4_optimizer.nvdm.parser import parse_nvdm_image

RACE_CHANNEL = 21
TOTAL_PEBS = 128
PAGES_PER_PEB = 16
PAGE_SIZE = 256
PEB_SIZE = PAGES_PER_PEB * PAGE_SIZE

MARKER_BASE = 0xDEAD0000


def dump_nvdm(bd_addr: str, label: str, out_dir: Path) -> bytes:
    """Dump 512KB NVDM via pipelined RACE PAGE_READ. Returns raw bytes."""
    print(f"\n[{label}] NVDM backup başlıyor...")
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


def send_recv_race(sock: socket.socket, pkt: RacePacket, timeout: float = 5.0) -> bytes:
    """Send RACE packet, receive response."""
    sock.sendall(pkt.to_bytes())
    data = b""
    sock.settimeout(timeout)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) >= RACE_HEADER_SIZE:
                _, _, length, _ = struct.unpack("<BBHH", data[:RACE_HEADER_SIZE])
                if len(data) >= RACE_HEADER_SIZE + length - 2:
                    break
    except socket.timeout:
        pass
    return data


def send_atci(sock: socket.socket, cmd: str, wait: float = 3.0) -> tuple[bytes, int]:
    """Send AT command via ATCI tunnel. Returns (payload, status_byte)."""
    req = AtciTunnelRequest(command=cmd)
    raw = send_recv_race(sock, req.to_packet(), timeout=wait)
    if len(raw) < RACE_HEADER_SIZE:
        return b"", 0xFF
    resp, _ = RacePacket.from_bytes(raw)
    status = resp.payload[2] if len(resp.payload) >= 3 else 0xFF
    return resp.payload, status


def send_ncoptset_commands(bd_addr: str, values: list[int]) -> list[tuple[int, int, bytes]]:
    """Send NCOPTSET for each word. Returns [(offset, status, payload), ...]."""
    sock = create_rfcomm_socket(bd_addr, RACE_CHANNEL, timeout_s=10.0)
    results = []

    try:
        # Enable relay mode
        pkt = RacePacket(head=0x05, type=0x5A, cmd_id=0x020C, payload=b"")
        raw = send_recv_race(sock, pkt)
        if raw:
            resp, _ = RacePacket.from_bytes(raw)
            print(f"  Relay mode: {resp.payload.hex()}")
        time.sleep(0.3)

        # Verify ATCI active
        payload, st = send_atci(sock, "AT")
        print(f"  AT probe: {payload.hex()} (status=0x{st:02X})")
        time.sleep(0.2)

        # Send NCOPTSET for each word
        for i, val in enumerate(values):
            cmd = f"AT+NCOPTTOOL=NCOPTSET,{i},0x{val:08X}"
            payload, st = send_atci(sock, cmd, wait=3.0)
            results.append((i, st, payload))
            print(f"  NCOPTSET[{i}] = 0x{val:08X} → status=0x{st:02X} resp={payload.hex()}")
            time.sleep(0.15)

        # Also try ENVDM=W as a second path
        print("\n  ENVDM komutları deneniyor...")
        marker_hex = "".join(f"{v:08X}" for v in values)

        for envdm_cmd in [
            f"AT+ENVDM=W,config,optimizer_coeff,{marker_hex}",
            f"AT+ENVDM=W,config,optimizer_coeff",
        ]:
            payload, st = send_atci(sock, envdm_cmd, wait=3.0)
            print(f"  {envdm_cmd[:60]}... → status=0x{st:02X} resp={payload.hex()}")
            time.sleep(0.2)

        # Try NCOPTGET/NCOPTDUMP to see current state
        print("\n  Okuma komutları...")
        for read_cmd in ["AT+NCOPTTOOL=NCOPTGET", "AT+NCOPTTOOL=NCOPTDUMP"]:
            payload, st = send_atci(sock, read_cmd, wait=5.0)
            print(f"  {read_cmd} → status=0x{st:02X} resp={payload.hex()} ({len(payload)}B)")
            time.sleep(0.2)

        # Disable relay
        pkt = RacePacket(head=0x05, type=0x5A, cmd_id=0x020D, payload=b"")
        send_recv_race(sock, pkt)
        print("  Relay kapatıldı")

    finally:
        sock.close()

    return results


def extract_optimizer_coeff(nvdm_bytes: bytes) -> tuple[bytes | None, list[int]]:
    """Parse NVDM image and extract config/optimizer_coeff value."""
    partition = parse_nvdm_image(nvdm_bytes)
    raw = partition.get_value("config", "optimizer_coeff")
    if raw is None:
        return None, []
    words = []
    for i in range(0, len(raw), 4):
        if i + 4 <= len(raw):
            words.append(struct.unpack(">I", raw[i:i+4])[0])
    return raw, words


def format_coeff_table(words: list[int], label: str) -> str:
    """Format coefficient words as a table."""
    labels = ["L:b0", "L:b1", "L:b2", "L:a1", "L:a2", "R:b0", "R:b1", "R:b2", "R:a1", "R:a2"]
    lines = [f"  {label}:"]
    for i, w in enumerate(words):
        marker = " ← MARKER" if (w & 0xFFFF0000) == MARKER_BASE else ""
        lbl = labels[i] if i < len(labels) else f"[{i}]"
        lines.append(f"    [{i}] {lbl:5s} = 0x{w:08X}{marker}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="NCOPTSET NVDM flash verification")
    parser.add_argument("--mac", default=None, help="BT MAC (auto-detect if omitted)")
    parser.add_argument("--out", type=Path, default=Path("verify_coefset_dumps"),
                        help="Output directory for NVDM dumps")
    parser.add_argument("--skip-baseline", action="store_true",
                        help="Skip baseline dump (reuse existing)")
    parser.add_argument("--skip-send", action="store_true",
                        help="Skip NCOPTSET send (only compare dumps)")
    parser.add_argument("--skip-post", action="store_true",
                        help="Skip post dump (do baseline + send only)")
    args = parser.parse_args()

    bd_addr = args.mac
    if bd_addr is None:
        from tools.backup_nvdm import find_connected_xm4_mac
        bd_addr = find_connected_xm4_mac()
        if bd_addr is None:
            print("Kulaklık bulunamadı. --mac ile belirt.")
            return 1
    print(f"Cihaz: {bd_addr}")

    args.out.mkdir(parents=True, exist_ok=True)

    # Marker values: unique pattern that cannot occur naturally
    marker_values = [MARKER_BASE + i for i in range(10)]

    # === ADIM 1: Baseline ===
    baseline_path = args.out / "nvdm_baseline.bin"
    if args.skip_baseline and baseline_path.exists():
        print(f"\nBaseline mevcut: {baseline_path}")
        baseline_bytes = baseline_path.read_bytes()
    else:
        baseline_bytes = dump_nvdm(bd_addr, "baseline", args.out)

    baseline_raw, baseline_words = extract_optimizer_coeff(baseline_bytes)
    if baseline_raw is None:
        print("HATA: config/optimizer_coeff baseline'da bulunamadı!")
        return 1

    print(f"\n{'='*60}")
    print(format_coeff_table(baseline_words, "BASELINE"))
    print(f"  Raw hex: {baseline_raw.hex()}")

    # === ADIM 2: NCOPTSET gönder ===
    if not args.skip_send:
        print(f"\n{'='*60}")
        print("ADIM 2: NCOPTSET komutları gönderiliyor...")
        print(f"  Marker pattern: 0x{MARKER_BASE:08X} + offset")
        results = send_ncoptset_commands(bd_addr, marker_values)

        # Immediate NVDM check (should NOT have changed yet — still in RAM)
        print(f"\n{'='*60}")
        print("Hemen sonra NVDM kontrolü (henüz değişmemeli)...")
        print("  Socket cleanup için 3 saniye bekleniyor...")
        time.sleep(3)
        immediate_bytes = dump_nvdm(bd_addr, "immediate", args.out)
        imm_raw, imm_words = extract_optimizer_coeff(immediate_bytes)
        if imm_raw:
            print(format_coeff_table(imm_words, "IMMEDIATE"))
            if imm_raw == baseline_raw:
                print("  → Beklendiği gibi: NVDM henüz değişmedi (RAM'de)")
            elif imm_words == marker_values:
                print("  → NCOPTSET doğrudan NVDM'e yazdı! (beklenmedik ama başarılı)")
                print("\n  *** KANITLI: NCOPTSET → NVDM doğrudan yazma çalışıyor ***")
                return 0
            else:
                print(f"  → NVDM değişti ama marker değil: {imm_raw.hex()}")

    # === ADIM 3: Power cycle bekleme ===
    if not args.skip_post:
        print(f"\n{'='*60}")
        print("ADIM 3: Power cycle gerekiyor")
        print("  Kulaklığı KAPAT (5 saniye basılı tut)")
        print("  30 saniye bekle")
        print("  Kulaklığı AÇ")
        print("  Bluetooth bağlantısını bekle")

        input("  Hazır olduğunda ENTER'a bas...")

        # Post-power-cycle NVDM dump
        post_bytes = dump_nvdm(bd_addr, "post_cycle", args.out)
        post_raw, post_words = extract_optimizer_coeff(post_bytes)
        if post_raw is None:
            print("HATA: config/optimizer_coeff post dump'ta bulunamadı!")
            return 1

        print(f"\n{'='*60}")
        print(format_coeff_table(post_words, "POST-CYCLE"))
        print(f"  Raw hex: {post_raw.hex()}")

        # === SONUÇ ===
        print(f"\n{'='*60}")
        print("SONUÇ")
        print(f"{'='*60}")

        if post_words == marker_values:
            print("  *** KANITLI: NCOPTSET → RAM → NVDM pipeline ÇALIŞIYOR ***")
            print(f"  Marker deseni NVDM'de bulundu: {[f'0x{v:08X}' for v in post_words]}")
            return 0
        elif post_raw == baseline_raw:
            print("  BAŞARISIZ: NVDM değişmedi.")
            print("  NCOPTSET ya RAM'e yazmıyor, ya da offset/format yanlış.")
            print("  Olası nedenler:")
            print("    - NCOPTSET offset 0-9 değil, farklı bir index")
            print("    - Firmware NCOPTSET'i relay modda işlemiyor")
            print("    - ATCI truncated response sorun yaratıyor")
            return 2
        else:
            print("  BELİRSİZ: NVDM değişti ama marker deseni değil.")
            print(f"  Baseline: {baseline_raw.hex()}")
            print(f"  Post:     {post_raw.hex()}")
            # Word-by-word comparison
            for i in range(min(len(baseline_words), len(post_words))):
                if baseline_words[i] != post_words[i]:
                    print(f"    [{i}] 0x{baseline_words[i]:08X} → 0x{post_words[i]:08X}")
            return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
