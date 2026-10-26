"""Tests for the known-firmware allowlist used by the flasher."""

from __future__ import annotations

from pathlib import Path

from tools import flash_firmware as flasher
from tools.flash_firmware import flash_firmware, parse_partition_info
from xm4_optimizer.firmware import KNOWN_FIRMWARE, KnownFirmware, identify_firmware


def test_table_entries_are_well_formed() -> None:
    assert len(KNOWN_FIRMWARE) == 5
    for digest, fw in KNOWN_FIRMWARE.items():
        assert len(digest) == 64 and int(digest, 16) >= 0
        assert fw.model_id == "MDRID294300" and fw.size > 1_000_000


def test_unknown_data_is_not_identified() -> None:
    assert identify_firmware(b"\x00" * 1395504) is None


def test_flasher_refuses_unknown_file_before_connecting(tmp_path: Path, monkeypatch) -> None:
    def no_socket(*_a, **_k):
        raise AssertionError("must not connect for an unknown image")

    monkeypatch.setattr("tools.flash_firmware.create_rfcomm_socket", no_socket)
    bogus = tmp_path / "custom.bin"
    bogus.write_bytes(b"\xff" * 4096)
    assert flash_firmware("00:11:22:33:44:55", bogus) is False


def test_partition_reply_and_fota_write_addresses(tmp_path: Path, monkeypatch) -> None:
    """The device's partition base and storage type must reach erase/page commands."""
    reply = bytes.fromhex("0000010000510000f05f00")
    assert parse_partition_info(reply) == (0, 1, 0x00510000, 0x005FF000)

    class Socket:
        def __init__(self):
            self.reads = 0

        def recv(self, _size):
            self.reads += 1
            return b"\x01" if self.reads <= 2 else b""

        def sendall(self, _data):
            pass

        def settimeout(self, _timeout):
            pass

        def close(self):
            pass

    requests = []

    class Race:
        def __init__(self, _sock):
            pass

        def request(self, command, payload=b"", **_kwargs):
            requests.append((command, bytes(payload)))
            return reply if command == flasher.CMD_PARTITION_INFO else b"\x00"

    monkeypatch.setattr(flasher, "create_rfcomm_socket", lambda *_a, **_kw: Socket())
    monkeypatch.setattr(flasher, "RaceClient", Race)
    monkeypatch.setattr(flasher, "identify_firmware", lambda _data: KnownFirmware("MDRID294300", "WH-1000XM4", "test", 512))
    image = tmp_path / "image.bin"
    image.write_bytes(b"\x11" * 256 + b"\x22" * 256)

    assert flash_firmware("00:11:22:33:44:55", image)
    assert (flasher.CMD_START_TRANSACTION, b"") in requests
    assert (flasher.CMD_WRITE_STATE, b"\x00\x02") in requests
    assert (flasher.CMD_ERASE, bytes.fromhex("010010000000005100")) in requests
    pages = [payload for command, payload in requests if command == flasher.CMD_PAGE_PROGRAM]
    assert len(pages) == 2
    assert pages[0][:7] == bytes([1, 1, flasher.page_crc(b"\x11" * 256)]) + bytes.fromhex("00005100")
    assert pages[1][:7] == bytes([1, 1, flasher.page_crc(b"\x22" * 256)]) + bytes.fromhex("00015100")
    assert pages[0][7:] == b"\x11" * 256
    assert pages[1][7:] == b"\x22" * 256
