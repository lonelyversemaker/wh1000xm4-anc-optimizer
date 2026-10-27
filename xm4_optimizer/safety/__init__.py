"""Safety, Checksum, Dry-Run, NCOPTSET Injection, Verification, and Rollback Engine."""

from xm4_optimizer.safety.checksum import (
    compute_bkdr_hash,
    compute_nvdm_checksum,
    compute_race_fota_crc8,
    verify_nvdm_checksum,
    verify_race_fota_crc8,
)
from xm4_optimizer.safety.dry_run import (
    CoefficientWordDiff,
    DryRunItemNotFoundError,
    DryRunReport,
    DryRunWriteViolationError,
    ReadOnlyTransportGuard,
    execute_dry_run,
    generate_dry_run_report,
)
from xm4_optimizer.safety.injector import (
    InjectionError,
    InjectionResult,
    UnstableFilterHoldError,
    execute_injection,
)
from xm4_optimizer.safety.rollback import (
    BackupMetadata,
    RollbackError,
    create_nvdm_backup,
    execute_rollback,
)
from xm4_optimizer.safety.verifier import (
    VerificationError,
    verify_dsp_registers_atci,
    verify_ncoptget_state,
    verify_nvdm_block_in_flash,
    verify_optimizer_coeff_in_nvdm,
    verify_readback,
)

__all__ = [
    "BackupMetadata",
    "CoefficientWordDiff",
    "DryRunItemNotFoundError",
    "DryRunReport",
    "DryRunWriteViolationError",
    "InjectionError",
    "InjectionResult",
    "ReadOnlyTransportGuard",
    "RollbackError",
    "UnstableFilterHoldError",
    "VerificationError",
    "compute_bkdr_hash",
    "compute_nvdm_checksum",
    "compute_race_fota_crc8",
    "create_nvdm_backup",
    "execute_dry_run",
    "execute_injection",
    "execute_rollback",
    "generate_dry_run_report",
    "verify_dsp_registers_atci",
    "verify_ncoptget_state",
    "verify_nvdm_block_in_flash",
    "verify_nvdm_checksum",
    "verify_optimizer_coeff_in_nvdm",
    "verify_race_fota_crc8",
    "verify_readback",
]
