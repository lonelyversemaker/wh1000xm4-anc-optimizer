"""Readback Verification Engine for NVDM and DSP Coefficient State.

Verifies:
1. config/optimizer_coeff in NVDM flash matches expected 40-byte payload.
2. NCOPTGET confirms DSP has received data (state change from null to present).

Limitation: ATCI relay truncates responses to 3 bytes, so exact coefficient readback
via NCOPTGET is not possible — only null/data-present detection works.
"""

from __future__ import annotations

from typing import List, Optional

from xm4_optimizer.nvdm.cxd90050 import (
    OptimizerCoefficient,
    OPTIMIZER_COEFF_GROUP,
    OPTIMIZER_COEFF_ITEM,
    OPTIMIZER_COEFF_SIZE,
)
from xm4_optimizer.nvdm.parser import parse_nvdm_image
from xm4_optimizer.transport.rfcomm_socket import (
    DeviceTransport,
    NVDM_PARTITION_BASE,
    NVDM_PARTITION_SIZE,
    read_nvdm_partition,
)


class VerificationError(Exception):
    """Raised when readback verification detects a mismatch."""

    def __init__(
        self,
        message: str,
        mismatch_offsets: List[int] | None = None,
        expected_byte: int | None = None,
        actual_byte: int | None = None,
    ) -> None:
        super().__init__(message)
        self.mismatch_offsets = mismatch_offsets or []
        self.expected_byte = expected_byte
        self.actual_byte = actual_byte


def verify_readback(injected_bytes: bytes, readback_bytes: bytes) -> bool:
    """Performs bit-exact comparison between injected bytes and readback bytes."""
    if len(injected_bytes) != len(readback_bytes):
        raise ValueError(
            f"Size mismatch: injected {len(injected_bytes)}B, read {len(readback_bytes)}B"
        )
    if injected_bytes != readback_bytes:
        mismatches = [
            i for i in range(len(injected_bytes)) if injected_bytes[i] != readback_bytes[i]
        ]
        first = mismatches[0]
        raise VerificationError(
            f"Bit mismatch at {len(mismatches)} offsets: first at offset 0x{first:04X} "
            f"(expected 0x{injected_bytes[first]:02X}, got 0x{readback_bytes[first]:02X})",
            mismatch_offsets=mismatches,
            expected_byte=injected_bytes[first],
            actual_byte=readback_bytes[first],
        )
    return True


def verify_ncoptget_state(transport: DeviceTransport) -> bool:
    """Checks whether NCOPTGET reports data-present (DSP has received coefficients).

    Due to 3-byte ATCI relay truncation, we can only detect null vs data-present,
    not read back exact coefficient values.
    """
    resp = transport.send_atci_command("AT+NCOPTTOOL=NCOPTGET")
    if "ERROR" in resp.upper():
        raise VerificationError(f"NCOPTGET failed: {resp!r}")
    has_data = "DSP1_NCOPT_DATA=" in resp
    if has_data:
        after_eq = resp.split("DSP1_NCOPT_DATA=")[1]
        if after_eq.startswith("\r") or after_eq.startswith("\n") or after_eq.strip() == "":
            return False
        return True
    return False


def verify_optimizer_coeff_in_nvdm(
    transport: DeviceTransport,
    expected_coeff: OptimizerCoefficient,
    base_addr: int = NVDM_PARTITION_BASE,
) -> bool:
    """Reads NVDM and verifies config/optimizer_coeff matches expected bytes."""
    image_bytes = read_nvdm_partition(transport, base_addr=base_addr, size=NVDM_PARTITION_SIZE)
    partition = parse_nvdm_image(image_bytes, strict=True)
    item = partition.get_item(OPTIMIZER_COEFF_GROUP, OPTIMIZER_COEFF_ITEM)
    if item is None:
        raise VerificationError(
            f"NVDM item {OPTIMIZER_COEFF_GROUP}/{OPTIMIZER_COEFF_ITEM} not found in flash readback"
        )
    if not item.is_checksum_valid:
        raise VerificationError(
            f"NVDM item {OPTIMIZER_COEFF_GROUP}/{OPTIMIZER_COEFF_ITEM} failed checksum in flash readback"
        )
    expected_bytes = expected_coeff.pack()
    return verify_readback(expected_bytes, item.value)


# Legacy aliases for backward compatibility with tests
def verify_dsp_registers_atci(transport: DeviceTransport, expected_block: object = None) -> bool:
    return verify_ncoptget_state(transport)


def verify_nvdm_block_in_flash(
    transport: DeviceTransport,
    expected_block: object = None,
    group_name: str = OPTIMIZER_COEFF_GROUP,
    item_name: str | None = None,
    base_addr: int = NVDM_PARTITION_BASE,
) -> bool:
    if expected_block is not None and hasattr(expected_block, "pack"):
        coeff = OptimizerCoefficient.unpack(expected_block.pack()[:OPTIMIZER_COEFF_SIZE]) if len(expected_block.pack()) >= OPTIMIZER_COEFF_SIZE else OptimizerCoefficient()
    else:
        coeff = OptimizerCoefficient()
    return verify_optimizer_coeff_in_nvdm(transport, coeff, base_addr=base_addr)
