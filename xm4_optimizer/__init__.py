"""Sony WH-1000XM4 ANC Optimizer package.

A modular optimization suite providing NVDM parameter extraction,
biquad IIR DSP coefficient synthesis, dry-run simulation, and safe injection
for Sony WH-1000XM4 active noise cancellation.
"""

from importlib import import_module

# Exports load on first access, so importing a light submodule (transport,
# firmware) does not pull in numpy through the DSP package.
_EXPORTS = {
    "BiquadCoefficients": "xm4_optimizer.dsp",
    "SynthesisResult": "xm4_optimizer.dsp",
    "synthesize_anc_filter": "xm4_optimizer.dsp",
    "verify_nyquist_stability": "xm4_optimizer.dsp",
    "CXD90050AlignmentBlock": "xm4_optimizer.nvdm",
    "NvdmPartition": "xm4_optimizer.nvdm",
    "OptimizerCoefficient": "xm4_optimizer.nvdm",
    "extract_cxd90050_blocks": "xm4_optimizer.nvdm",
    "parse_nvdm_image": "xm4_optimizer.nvdm",
    "execute_dry_run": "xm4_optimizer.safety",
    "execute_injection": "xm4_optimizer.safety",
    "execute_rollback": "xm4_optimizer.safety",
    "verify_readback": "xm4_optimizer.safety",
    "BluetoothRfcommTransport": "xm4_optimizer.transport",
    "DeviceTransport": "xm4_optimizer.transport",
    "VirtualXM4Device": "xm4_optimizer.transport",
}


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'xm4_optimizer' has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


__version__ = "0.1.0"

__all__ = [
    "BiquadCoefficients",
    "BluetoothRfcommTransport",
    "CXD90050AlignmentBlock",
    "DeviceTransport",
    "NvdmPartition",
    "OptimizerCoefficient",
    "SynthesisResult",
    "VirtualXM4Device",
    "__version__",
    "execute_dry_run",
    "execute_injection",
    "execute_rollback",
    "extract_cxd90050_blocks",
    "parse_nvdm_image",
    "synthesize_anc_filter",
    "verify_nyquist_stability",
    "verify_readback",
]
