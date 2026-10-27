"""Firmware Power-Cycle Emulation Tests.

Tests the VirtualXM4Device.power_cycle() method which emulates:
- Power-off: FUN_082bb5d8 — saves optimizer_ram_buffer to NVDM as config/optimizer_coeff
- Power-on: FUN_082bb468 — reads config/optimizer_coeff from NVDM, restores to RAM + DSP

Evidence basis: Ghidra decompilation of v2.5.0 section 4 (docs/STATUS.md).
"""

from __future__ import annotations

from pathlib import Path
import pytest

from xm4_optimizer.dsp.synthesizer import synthesize_optimizer_coeff
from xm4_optimizer.nvdm.cxd90050 import (
    OptimizerCoefficient,
    OPTIMIZER_COEFF_IDENTITY,
)
from xm4_optimizer.nvdm.parser import parse_nvdm_image
from xm4_optimizer.safety.injector import execute_injection
from xm4_optimizer.safety.rollback import create_nvdm_backup, execute_rollback
from xm4_optimizer.transport.virtual_device import VirtualXM4Device


class TestPowerCycleOptimistic:
    """NCOPTSET updates RAM buffer → power-off saves to NVDM → power-on restores."""

    def test_ncoptset_persists_through_power_cycle(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()

        marker_words = [0xDEADBE00 + i for i in range(10)]
        for i, w in enumerate(marker_words):
            dev.send_atci_command(f"AT+NCOPTTOOL=NCOPTSET,{i},0x{w:08X}")

        assert dev.ncopt_data == marker_words
        assert dev.optimizer_ram_buffer == marker_words

        dev.power_cycle()

        assert dev.ncopt_data == marker_words
        assert dev.optimizer_ram_buffer == marker_words
        assert dev.is_connected is True

        partition = parse_nvdm_image(bytes(dev.flash), strict=False)
        item = partition.get_item("config", "optimizer_coeff")
        assert item is not None
        coeff = OptimizerCoefficient.unpack(item.value)
        assert coeff.words == marker_words

    def test_inject_pipeline_persists_through_power_cycle(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()

        opt_coeff, _ = synthesize_optimizer_coeff(target_gain_db=7.5, fs=48000.0)
        result = execute_injection(dev, opt_coeff)
        assert result.success is True

        dev.power_cycle()

        assert dev.ncopt_data == opt_coeff.words

        partition = parse_nvdm_image(bytes(dev.flash), strict=False)
        item = partition.get_item("config", "optimizer_coeff")
        coeff = OptimizerCoefficient.unpack(item.value)
        assert coeff.words == opt_coeff.words


class TestPowerCyclePessimistic:
    """NCOPTSET bypasses RAM buffer → power-off saves old values → NCOPTSET values lost."""

    def test_ncoptset_bypass_loses_values_on_power_cycle(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()
        dev._ncoptset_updates_ram = False

        marker_words = [0xCAFE0000 + i for i in range(10)]
        for i, w in enumerate(marker_words):
            dev.send_atci_command(f"AT+NCOPTTOOL=NCOPTSET,{i},0x{w:08X}")

        assert dev.ncopt_data == marker_words
        assert dev.optimizer_ram_buffer == list(OPTIMIZER_COEFF_IDENTITY)

        dev.power_cycle()

        assert dev.ncopt_data == list(OPTIMIZER_COEFF_IDENTITY)
        assert dev.optimizer_ram_buffer == list(OPTIMIZER_COEFF_IDENTITY)

    def test_pessimistic_nvdm_contains_identity_not_ncoptset(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()
        dev._ncoptset_updates_ram = False

        for i in range(10):
            dev.send_atci_command(f"AT+NCOPTTOOL=NCOPTSET,{i},0x{0xBAADF00D:08X}")

        dev.power_cycle()

        partition = parse_nvdm_image(bytes(dev.flash), strict=False)
        item = partition.get_item("config", "optimizer_coeff")
        coeff = OptimizerCoefficient.unpack(item.value)
        assert coeff.words == list(OPTIMIZER_COEFF_IDENTITY)


class TestPowerCycleFullLifecycle:
    """Full inject → power_cycle → verify → rollback → power_cycle → verify identity."""

    def test_full_lifecycle_with_power_cycles(self, tmp_path: Path) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()

        backup_path = tmp_path / "backup.bin"
        create_nvdm_backup(dev, backup_path)

        opt_coeff, _ = synthesize_optimizer_coeff(target_gain_db=8.0, fs=48000.0)
        execute_injection(dev, opt_coeff)
        assert dev.ncopt_data == opt_coeff.words

        dev.power_cycle()

        partition = parse_nvdm_image(bytes(dev.flash), strict=False)
        item = partition.get_item("config", "optimizer_coeff")
        assert OptimizerCoefficient.unpack(item.value).words == opt_coeff.words

        execute_rollback(dev, backup_path, verify=True)

        dev.power_cycle()

        partition2 = parse_nvdm_image(bytes(dev.flash), strict=False)
        item2 = partition2.get_item("config", "optimizer_coeff")
        coeff2 = OptimizerCoefficient.unpack(item2.value)
        assert coeff2.is_identity
        assert dev.ncopt_data == list(OPTIMIZER_COEFF_IDENTITY)


class TestPowerCycleMultipleRounds:
    """Multiple inject + power_cycle rounds — last value wins in NVDM."""

    def test_successive_injects_last_value_persists(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()

        coeff1, _ = synthesize_optimizer_coeff(target_gain_db=6.5, fs=48000.0)
        execute_injection(dev, coeff1)
        dev.power_cycle()

        coeff2, _ = synthesize_optimizer_coeff(target_gain_db=8.5, fs=48000.0)
        execute_injection(dev, coeff2)
        dev.power_cycle()

        assert dev.ncopt_data == coeff2.words
        assert dev.ncopt_data != coeff1.words

        partition = parse_nvdm_image(bytes(dev.flash), strict=False)
        item = partition.get_item("config", "optimizer_coeff")
        assert OptimizerCoefficient.unpack(item.value).words == coeff2.words

    def test_three_cycles_sequence_numbers_increase(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()

        for gain in (6.0, 7.0, 8.0):
            coeff, _ = synthesize_optimizer_coeff(target_gain_db=gain, fs=48000.0)
            execute_injection(dev, coeff)
            dev.power_cycle()

        partition = parse_nvdm_image(bytes(dev.flash), strict=False)
        item = partition.get_item("config", "optimizer_coeff")
        assert item is not None
        assert item.header.sequence_number > 9  # seed uses seq 1-8, 3 cycles added more


class TestPowerCycleByteOrder:
    """Verifies big-endian Q4.28 round-trip matches firmware byte-swap behavior."""

    def test_be_q428_round_trip_integrity(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()

        test_words = [0x10000000, 0xE3B571CF, 0x1C4A8E31, 0xF0000000, 0x0FFFFFFF,
                      0x10000000, 0x00000000, 0x00000000, 0x00000000, 0x00000000]
        for i, w in enumerate(test_words):
            dev.send_atci_command(f"AT+NCOPTTOOL=NCOPTSET,{i},0x{w:08X}")

        dev.power_cycle()

        partition = parse_nvdm_image(bytes(dev.flash), strict=False)
        item = partition.get_item("config", "optimizer_coeff")
        coeff = OptimizerCoefficient.unpack(item.value)

        assert coeff.words == test_words

        packed = coeff.pack()
        import struct
        unpacked = list(struct.unpack(">10I", packed))
        assert unpacked == test_words
