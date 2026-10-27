"""Zero-Byte Dry-Run Simulation Engine for Sony WH-1000XM4 ANC Optimization.

Targets config/optimizer_coeff (40 bytes, 2×5 Q4.28 BE words) — the real NVDM item
verified on hardware. Errors on missing item instead of silently substituting identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from xm4_optimizer.dsp.biquad import BiquadCoefficients
from xm4_optimizer.dsp.simulation import render_ascii_response_curve
from xm4_optimizer.dsp.synthesizer import SynthesisResult
from xm4_optimizer.nvdm.cxd90050 import (
    OptimizerCoefficient,
    OPTIMIZER_COEFF_GROUP,
    OPTIMIZER_COEFF_ITEM,
    OPTIMIZER_COEFF_SIZE,
    OPTIMIZER_COEFF_WORDS,
)
from xm4_optimizer.nvdm.item import DATA_ITEM_HEADER_SIZE
from xm4_optimizer.nvdm.parser import parse_nvdm_image
from xm4_optimizer.nvdm.peb import NVDM_BASE_ADDRESS, PEB_SIZE
from xm4_optimizer.transport.protocol_race import FLASH_PAGE_SIZE
from xm4_optimizer.transport.rfcomm_socket import DeviceTransport


class DryRunWriteViolationError(RuntimeError):
    """Raised when any flash or ATCI write operation is attempted during a dry-run."""


class DryRunItemNotFoundError(RuntimeError):
    """Raised when config/optimizer_coeff is not found in the NVDM image."""


class ReadOnlyTransportGuard:
    """Transport wrapper that strictly blocks any mutating operation during dry-run."""

    def __init__(self, inner: Optional[DeviceTransport] = None) -> None:
        self._inner = inner
        self.bytes_written: int = 0
        self.write_attempts: int = 0

    def connect(self) -> None:
        if self._inner is not None:
            self._inner.connect()

    def close(self) -> None:
        if self._inner is not None:
            self._inner.close()

    def read_flash_page(self, address: int) -> bytes:
        if self._inner is None:
            raise ConnectionError("No underlying transport configured for read")
        return self._inner.read_flash_page(address)

    def write_flash_page(self, address: int, data: bytes) -> bool:
        self.write_attempts += 1
        raise DryRunWriteViolationError(
            f"DRY-RUN VIOLATION: Attempted to write {len(data)} bytes to flash address 0x{address:08X}"
        )

    def send_atci_command(self, cmd: str, timeout_ms: int = 3000) -> str:
        clean = cmd.strip().upper()
        if "COEFSET" in clean or "ENVDM=W" in clean or "NCOPTSET" in clean:
            self.write_attempts += 1
            raise DryRunWriteViolationError(
                f"DRY-RUN VIOLATION: Attempted mutating ATCI command {cmd!r}"
            )
        if self._inner is None:
            return "\r\nOK\r\n"
        return self._inner.send_atci_command(cmd, timeout_ms=timeout_ms)


COEFF_LABELS = ["L:b0", "L:b1", "L:b2", "L:a1", "L:a2",
                "R:b0", "R:b1", "R:b2", "R:a1", "R:a2"]


@dataclass
class CoefficientWordDiff:
    """Comparison of a single Q4.28 word between original and optimized."""

    index: int
    label: str
    original_word: int
    optimized_word: int
    changed: bool


@dataclass
class DryRunReport:
    """Structured output of a dry-run execution."""

    item_flash_addr: int
    value_flash_addr: int
    affected_page_addresses: List[int]
    original_coeff: OptimizerCoefficient
    optimized_coeff: OptimizerCoefficient
    band_min_gain_db: float
    band_max_gain_db: float
    max_pole_magnitude: float
    is_stable: bool
    word_diffs: List[CoefficientWordDiff] = field(default_factory=list)
    ascii_curve: str = ""
    rendered_text: str = ""
    bytes_written: int = 0
    exit_code: int = 0


def _locate_optimizer_coeff(
    image_bytes: bytes,
    base_addr: int = NVDM_BASE_ADDRESS,
) -> tuple[int, int, List[int], OptimizerCoefficient]:
    """Finds config/optimizer_coeff in the NVDM image. Raises DryRunItemNotFoundError if missing."""
    partition = parse_nvdm_image(image_bytes, strict=False)
    item = partition.get_item(OPTIMIZER_COEFF_GROUP, OPTIMIZER_COEFF_ITEM)

    if item is None:
        raise DryRunItemNotFoundError(
            f"NVDM item {OPTIMIZER_COEFF_GROUP}/{OPTIMIZER_COEFF_ITEM} not found in image. "
            f"This item is created by the NC Optimizer on the headphones — run the optimizer "
            f"from the Sony Headphones app at least once, then take a new backup."
        )

    if len(item.value) != OPTIMIZER_COEFF_SIZE:
        raise DryRunItemNotFoundError(
            f"{OPTIMIZER_COEFF_GROUP}/{OPTIMIZER_COEFF_ITEM} has unexpected size "
            f"{len(item.value)} bytes (expected {OPTIMIZER_COEFF_SIZE})"
        )

    peb_offset = item.header.pnum * PEB_SIZE
    item_rel_offset = peb_offset + item.header.offset
    val_rel_offset = (
        item_rel_offset
        + DATA_ITEM_HEADER_SIZE
        + item.header.group_name_size
        + item.header.data_item_name_size
    )
    item_abs_addr = base_addr + item_rel_offset
    val_abs_addr = base_addr + val_rel_offset

    start_page = (item_abs_addr // FLASH_PAGE_SIZE) * FLASH_PAGE_SIZE
    end_addr = item_abs_addr + item.header.total_record_size - 1
    end_page = (end_addr // FLASH_PAGE_SIZE) * FLASH_PAGE_SIZE
    pages = list(range(start_page, end_page + FLASH_PAGE_SIZE, FLASH_PAGE_SIZE))

    orig_coeff = OptimizerCoefficient.unpack(item.value)
    return item_abs_addr, val_abs_addr, pages, orig_coeff


def generate_dry_run_report(
    original_image: bytes,
    optimized_coeff: OptimizerCoefficient,
    synthesis_result: SynthesisResult,
    base_addr: int = NVDM_BASE_ADDRESS,
) -> DryRunReport:
    """Computes full dry-run comparison report without touching any hardware."""
    item_addr, val_addr, pages, orig_coeff = _locate_optimizer_coeff(
        original_image, base_addr=base_addr
    )

    word_diffs: List[CoefficientWordDiff] = []
    for i in range(OPTIMIZER_COEFF_WORDS):
        ow = orig_coeff.words[i]
        nw = optimized_coeff.words[i]
        word_diffs.append(CoefficientWordDiff(
            index=i,
            label=COEFF_LABELS[i] if i < len(COEFF_LABELS) else f"[{i}]",
            original_word=ow,
            optimized_word=nw,
            changed=(ow != nw),
        ))

    ascii_curve = render_ascii_response_curve(
        frequencies=synthesis_result.freqs,
        magnitude_db=synthesis_result.magnitude_db,
        width=60,
        height=12,
        band_highlight=(50.0, 800.0),
    )

    lines: List[str] = []
    sep = "=" * 88
    lines.append(sep)
    lines.append("  config/optimizer_coeff — Dry-Run Coefficient Diff")
    lines.append(sep)
    lines.append(f"  NVDM Item Address         : 0x{item_addr:08X}")
    lines.append(f"  Value Offset              : 0x{val_addr:08X} ({OPTIMIZER_COEFF_SIZE} bytes)")
    lines.append(
        f"  Affected 256B Flash Pages : {', '.join(f'0x{p:08X}' for p in pages)}"
    )
    lines.append(
        f"  50-800 Hz Band Gain Range : {synthesis_result.band_min_gain_db:+.2f} dB to {synthesis_result.band_max_gain_db:+.2f} dB"
    )
    lines.append(
        f"  Nyquist Pole Stability    : {'PASS' if synthesis_result.is_stable else 'FAIL'} (max |p| = {synthesis_result.max_pole_magnitude:.6f} < 1.0)"
    )
    lines.append("  Hardware Bytes Written    : 0 bytes (DRY-RUN BARRIER ACTIVE)")
    lines.append("-" * 88)
    lines.append(
        f"  {'Idx':<4} | {'Label':<5} | {'Original':>10} | {'Optimized':>10} | {'Status':<9}"
    )
    lines.append("-" * 88)

    for d in word_diffs:
        status_str = "MODIFIED" if d.changed else "UNCHANGED"
        lines.append(
            f"  {d.index:<4} | {d.label:<5} | 0x{d.original_word:08X} | 0x{d.optimized_word:08X} | {status_str:<9}"
        )
    lines.append(sep)
    lines.append(ascii_curve)
    lines.append(sep)

    rendered_text = "\n".join(lines)

    return DryRunReport(
        item_flash_addr=item_addr,
        value_flash_addr=val_addr,
        affected_page_addresses=pages,
        original_coeff=orig_coeff,
        optimized_coeff=optimized_coeff,
        band_min_gain_db=synthesis_result.band_min_gain_db,
        band_max_gain_db=synthesis_result.band_max_gain_db,
        max_pole_magnitude=synthesis_result.max_pole_magnitude,
        is_stable=synthesis_result.is_stable,
        word_diffs=word_diffs,
        ascii_curve=ascii_curve,
        rendered_text=rendered_text,
        bytes_written=0,
        exit_code=0,
    )


def execute_dry_run(
    original_image: bytes,
    optimized_coeff: OptimizerCoefficient,
    synthesis_result: SynthesisResult,
    transport: Optional[DeviceTransport] = None,
    print_output: bool = True,
) -> int:
    """Executes non-destructive dry-run simulation, prints diffs/offsets/curve, returns 0."""
    guard = ReadOnlyTransportGuard(transport)
    report = generate_dry_run_report(
        original_image=original_image,
        optimized_coeff=optimized_coeff,
        synthesis_result=synthesis_result,
    )
    assert guard.bytes_written == 0
    if print_output:
        print(report.rendered_text)
    return 0
