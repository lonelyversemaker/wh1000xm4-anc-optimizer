"""Test Suite for Safety, Dry-Run, NCOPTSET Injection, Verifier & Rollback."""

from __future__ import annotations

from pathlib import Path
import pytest

from xm4_optimizer.dsp.biquad import BiquadCoefficients
from xm4_optimizer.dsp.synthesizer import synthesize_optimizer_coeff
from xm4_optimizer.nvdm.cxd90050 import (
    OptimizerCoefficient,
    OPTIMIZER_COEFF_IDENTITY,
)
from xm4_optimizer.nvdm.parser import parse_nvdm_image
from xm4_optimizer.safety.checksum import (
    compute_bkdr_hash,
    compute_nvdm_checksum,
    compute_race_fota_crc8,
    verify_nvdm_checksum,
    verify_race_fota_crc8,
)
from xm4_optimizer.safety.dry_run import (
    DryRunWriteViolationError,
    ReadOnlyTransportGuard,
    execute_dry_run,
    generate_dry_run_report,
)
from xm4_optimizer.safety.injector import (
    InjectionError,
    UnstableFilterHoldError,
    execute_injection,
)
from xm4_optimizer.safety.rollback import (
    RollbackError,
    create_nvdm_backup,
    execute_rollback,
)
from xm4_optimizer.safety.verifier import (
    VerificationError,
    verify_ncoptget_state,
    verify_readback,
)
from xm4_optimizer.transport.virtual_device import VirtualXM4Device


class TestChecksums:
    """Tests NVDM 16-bit interleaved checksum, BKDR hash, and RACE CRC-8."""

    def test_nvdm_checksum_deterministic_and_verify(self) -> None:
        payload = b"SONY_WH1000XM4_CXD90050_CALIBRATION_DATA_BLOCK"
        chk = compute_nvdm_checksum(payload)
        assert 0 <= chk <= 0xFFFF
        assert verify_nvdm_checksum(payload, chk) is True
        assert verify_nvdm_checksum(payload, chk ^ 0x0001) is False

    def test_race_fota_crc8_verification(self) -> None:
        page = bytes(range(256))
        crc = compute_race_fota_crc8(page)
        assert 0 <= crc <= 0xFF
        assert verify_race_fota_crc8(page, crc) is True
        assert verify_race_fota_crc8(page, (crc + 1) & 0xFF) is False

    def test_bkdr_hash_consistency(self) -> None:
        h1 = compute_bkdr_hash("DNC", "ALIGN_FF_L")
        h2 = compute_bkdr_hash("DNC", "ALIGN_FF_R")
        assert h1 != h2
        assert 0 <= h1 <= 0xFFFFFFFF


class TestZeroByteDryRun:
    """Verifies dry-run writes 0 bytes and targets config/optimizer_coeff."""

    def test_dry_run_writes_strictly_zero_bytes(self, capsys: pytest.CaptureFixture[str]) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()
        snapshot_before = bytes(dev.flash)

        opt_coeff, syn_res = synthesize_optimizer_coeff(target_gain_db=7.5, fs=48000.0)
        rc = execute_dry_run(
            original_image=snapshot_before,
            optimized_coeff=opt_coeff,
            synthesis_result=syn_res,
            transport=dev,
            print_output=True,
        )

        captured = capsys.readouterr().out
        assert rc == 0
        assert dev.write_count == 0
        assert bytes(dev.flash) == snapshot_before
        assert "config/optimizer_coeff" in captured
        assert "MODIFIED" in captured
        assert "0 bytes (DRY-RUN BARRIER ACTIVE)" in captured

    def test_read_only_transport_guard_blocks_flash_and_atci_writes(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()
        guard = ReadOnlyTransportGuard(dev)

        page0 = guard.read_flash_page(0x000DF000)
        assert len(page0) == 256

        with pytest.raises(DryRunWriteViolationError, match="DRY-RUN VIOLATION"):
            guard.write_flash_page(0x000DF000, b"\x00" * 256)

        with pytest.raises(DryRunWriteViolationError, match="DRY-RUN VIOLATION"):
            guard.send_atci_command("AT+NCOPTTOOL=NCOPTSET,0,0x10000000")

        with pytest.raises(DryRunWriteViolationError, match="DRY-RUN VIOLATION"):
            guard.send_atci_command("AT+ENVDM=W")

        assert dev.write_count == 0
        assert guard.bytes_written == 0
        assert guard.write_attempts == 3

    def test_generate_dry_run_report_structure(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()
        opt_coeff, syn_res = synthesize_optimizer_coeff(target_gain_db=8.0, fs=48000.0)
        report = generate_dry_run_report(bytes(dev.flash), opt_coeff, syn_res)

        assert report.exit_code == 0
        assert report.bytes_written == 0
        assert report.is_stable is True
        assert report.max_pole_magnitude < 1.0
        assert 6.0 <= report.band_max_gain_db <= 9.0
        assert len(report.word_diffs) == 10  # 2 biquads * 5 coefficients
        assert any(d.changed for d in report.word_diffs)
        assert len(report.ascii_curve.splitlines()) >= 10


class TestNCOPTSETInjectionAndVerification:
    """Verifies NCOPTSET injection, stability gate, and NCOPTGET verification."""

    def test_successful_injection_via_ncoptset(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()

        opt_coeff, _ = synthesize_optimizer_coeff(target_gain_db=7.5, fs=48000.0)

        result = execute_injection(dev, opt_coeff)
        assert result.success is True
        assert result.words_sent == 10
        assert result.ncoptget_confirmed is True
        assert dev.ncopt_data is not None
        assert dev.ncopt_data == opt_coeff.words

    def test_unstable_filter_rejected_before_any_write(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()
        assert dev.ncopt_data is None

        unstable_bq = BiquadCoefficients(a1=-2.4, a2=1.44, b0=1.0, b1=0.0, b2=0.0)
        identity_bq = BiquadCoefficients.passthrough()
        unstable_coeff = OptimizerCoefficient.from_biquads([unstable_bq, identity_bq])

        with pytest.raises(UnstableFilterHoldError, match="UNSTABLE FILTER REJECTED"):
            execute_injection(dev, unstable_coeff)

        assert dev.ncopt_data is None

    def test_ncoptget_state_detection(self) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()

        assert verify_ncoptget_state(dev) is False

        opt_coeff, _ = synthesize_optimizer_coeff(target_gain_db=7.5, fs=48000.0)
        execute_injection(dev, opt_coeff, verify=False)

        assert verify_ncoptget_state(dev) is True

    def test_verify_readback_detects_single_bit_flip(self) -> None:
        expected = bytes(range(40))
        assert verify_readback(expected, expected) is True

        corrupted = bytearray(expected)
        corrupted[20] ^= 0x01
        with pytest.raises(VerificationError) as exc_info:
            verify_readback(expected, bytes(corrupted))
        assert 20 in exc_info.value.mismatch_offsets
        assert exc_info.value.expected_byte == 20
        assert exc_info.value.actual_byte == (20 ^ 0x01)


class TestBackupAndRollback:
    """Verifies NVDM backup (512 KB) and NCOPTSET-based identity rollback."""

    def test_full_backup_and_ncoptset_rollback(self, tmp_path: Path) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()

        backup_file = tmp_path / "xm4_nvdm_backup.bin"
        meta = create_nvdm_backup(dev, backup_file)

        assert backup_file.exists()
        assert meta.sidecar_sha256_path.exists()
        assert meta.size_bytes == 524288  # 512 KB
        assert meta.active_item_count == 8  # 7 DNC + 1 config/optimizer_coeff

        opt_coeff, _ = synthesize_optimizer_coeff(target_gain_db=8.5, fs=48000.0)
        execute_injection(dev, opt_coeff)
        assert dev.ncopt_data == opt_coeff.words

        ok = execute_rollback(dev, backup_file, verify=True)
        assert ok is True

        identity = OptimizerCoefficient()
        assert dev.ncopt_data == identity.words

    def test_rollback_rejects_corrupted_sha256_sidecar(self, tmp_path: Path) -> None:
        dev = VirtualXM4Device(populate_defaults=True)
        dev.connect()
        backup_file = tmp_path / "corrupt_backup.bin"
        meta = create_nvdm_backup(dev, backup_file)

        tampered = bytearray(backup_file.read_bytes())
        tampered[100] ^= 0xFF
        backup_file.write_bytes(bytes(tampered))

        with pytest.raises(RollbackError, match="SHA-256 sidecar mismatch"):
            execute_rollback(dev, backup_file)
