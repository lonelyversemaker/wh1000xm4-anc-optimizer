"""Sony WH-1000XM4 DSP & Mathematical Synthesis Subsystem.

Provides:
- 5-coefficient 2nd-order IIR biquad models and sign convention handling
- Fixed-point Q28 / Q31 conversions, clamping, and binary packing (<5i)
- RBJ Low-Shelf, Peaking EQ, and Subsonic High-Pass filter synthesis
- Discrete-time characteristic root calculation, Schur-Cohn & Nyquist stability proofs
- Complex DTFT frequency response simulation and ASCII curve plotting
"""

from importlib import import_module

# Exports load on first access: fixed_point is pure Python and is imported by the
# NVDM parser, while the other submodules need numpy.
_EXPORTS = {
    # biquad
    "BiquadCascade": "xm4_optimizer.dsp.biquad",
    "BiquadCoefficients": "xm4_optimizer.dsp.biquad",
    "BiquadFilter": "xm4_optimizer.dsp.biquad",
    "SignConvention": "xm4_optimizer.dsp.biquad",
    "detect_sign_convention": "xm4_optimizer.dsp.biquad",
    # fixed_point
    "BIQUAD_BYTE_SIZE": "xm4_optimizer.dsp.fixed_point",
    "BIQUAD_STRUCT_FORMAT": "xm4_optimizer.dsp.fixed_point",
    "INT32_MAX": "xm4_optimizer.dsp.fixed_point",
    "INT32_MIN": "xm4_optimizer.dsp.fixed_point",
    "Q28_FRAC_BITS": "xm4_optimizer.dsp.fixed_point",
    "Q28_MAX_FLOAT": "xm4_optimizer.dsp.fixed_point",
    "Q28_MIN_FLOAT": "xm4_optimizer.dsp.fixed_point",
    "Q28_RESOLUTION": "xm4_optimizer.dsp.fixed_point",
    "Q28_SCALE": "xm4_optimizer.dsp.fixed_point",
    "Q31_FRAC_BITS": "xm4_optimizer.dsp.fixed_point",
    "Q31_MAX_FLOAT": "xm4_optimizer.dsp.fixed_point",
    "Q31_MIN_FLOAT": "xm4_optimizer.dsp.fixed_point",
    "Q31_RESOLUTION": "xm4_optimizer.dsp.fixed_point",
    "Q31_SCALE": "xm4_optimizer.dsp.fixed_point",
    "clamp_int32": "xm4_optimizer.dsp.fixed_point",
    "float_to_q28": "xm4_optimizer.dsp.fixed_point",
    "float_to_q31": "xm4_optimizer.dsp.fixed_point",
    "pack_biquad_q28": "xm4_optimizer.dsp.fixed_point",
    "pack_biquad_q31": "xm4_optimizer.dsp.fixed_point",
    "q28_to_float": "xm4_optimizer.dsp.fixed_point",
    "q31_to_float": "xm4_optimizer.dsp.fixed_point",
    "unpack_biquad_q28": "xm4_optimizer.dsp.fixed_point",
    "unpack_biquad_q31": "xm4_optimizer.dsp.fixed_point",
    # simulation
    "AttenuationBandViolationError": "xm4_optimizer.dsp.simulation",
    "BandVerificationResult": "xm4_optimizer.dsp.simulation",
    "FrequencyResponse": "xm4_optimizer.dsp.simulation",
    "assert_attenuation_band": "xm4_optimizer.dsp.simulation",
    "create_frequency_grid": "xm4_optimizer.dsp.simulation",
    "evaluate_alignment_block_dtft": "xm4_optimizer.dsp.simulation",
    "evaluate_biquad_dtft": "xm4_optimizer.dsp.simulation",
    "evaluate_cascade_dtft": "xm4_optimizer.dsp.simulation",
    "render_ascii_response_curve": "xm4_optimizer.dsp.simulation",
    "verify_attenuation_band": "xm4_optimizer.dsp.simulation",
    # stability
    "FilterInstabilityError": "xm4_optimizer.dsp.stability",
    "PolePair": "xm4_optimizer.dsp.stability",
    "QuantizationStabilityReport": "xm4_optimizer.dsp.stability",
    "StabilityMargin": "xm4_optimizer.dsp.stability",
    "StabilityReport": "xm4_optimizer.dsp.stability",
    "assert_biquad_stable": "xm4_optimizer.dsp.stability",
    "check_schur_cohn": "xm4_optimizer.dsp.stability",
    "compute_biquad_poles": "xm4_optimizer.dsp.stability",
    "compute_characteristic_roots": "xm4_optimizer.dsp.stability",
    "compute_stability_margins": "xm4_optimizer.dsp.stability",
    "is_biquad_stable": "xm4_optimizer.dsp.stability",
    "validate_alignment_block_stability": "xm4_optimizer.dsp.stability",
    "verify_nyquist_stability": "xm4_optimizer.dsp.stability",
    "verify_quantization_invariance": "xm4_optimizer.dsp.stability",
    # synthesizer
    "ATTENUATION_MAX_ALLOWED_DB": "xm4_optimizer.dsp.synthesizer",
    "ATTENUATION_MIN_REQUIRED_DB": "xm4_optimizer.dsp.synthesizer",
    "CXD90050_BIQUAD_COUNT": "xm4_optimizer.dsp.synthesizer",
    "DEFAULT_BOOST_GAIN_DB": "xm4_optimizer.dsp.synthesizer",
    "DEFAULT_SAMPLE_RATE": "xm4_optimizer.dsp.synthesizer",
    "DEFAULT_SHELF_F0": "xm4_optimizer.dsp.synthesizer",
    "DEFAULT_SHELF_SLOPE": "xm4_optimizer.dsp.synthesizer",
    "SUBSONIC_HPF_DEFAULT_F0": "xm4_optimizer.dsp.synthesizer",
    "SUBSONIC_HPF_DEFAULT_Q": "xm4_optimizer.dsp.synthesizer",
    "SUPPORTED_SAMPLE_RATES": "xm4_optimizer.dsp.synthesizer",
    "TARGET_BAND_DEFAULT": "xm4_optimizer.dsp.synthesizer",
    "SynthesisResult": "xm4_optimizer.dsp.synthesizer",
    "calculate_biquad_poles": "xm4_optimizer.dsp.synthesizer",
    "create_alignment_block": "xm4_optimizer.dsp.synthesizer",
    "create_identity_biquad": "xm4_optimizer.dsp.synthesizer",
    "pad_biquad_cascade": "xm4_optimizer.dsp.synthesizer",
    "synthesize_anc_boost": "xm4_optimizer.dsp.synthesizer",
    "synthesize_anc_filter": "xm4_optimizer.dsp.synthesizer",
    "synthesize_high_pass": "xm4_optimizer.dsp.synthesizer",
    "synthesize_low_shelf": "xm4_optimizer.dsp.synthesizer",
    "synthesize_peaking_eq": "xm4_optimizer.dsp.synthesizer",
}


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'xm4_optimizer.dsp' has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


__all__ = [
    # Biquad
    "BiquadCascade",
    "BiquadCoefficients",
    "BiquadFilter",
    "SignConvention",
    "detect_sign_convention",
    # Fixed point
    "INT32_MIN",
    "INT32_MAX",
    "Q28_FRAC_BITS",
    "Q28_SCALE",
    "Q28_MIN_FLOAT",
    "Q28_MAX_FLOAT",
    "Q28_RESOLUTION",
    "Q31_FRAC_BITS",
    "Q31_SCALE",
    "Q31_MIN_FLOAT",
    "Q31_MAX_FLOAT",
    "Q31_RESOLUTION",
    "BIQUAD_STRUCT_FORMAT",
    "BIQUAD_BYTE_SIZE",
    "clamp_int32",
    "float_to_q28",
    "q28_to_float",
    "float_to_q31",
    "q31_to_float",
    "pack_biquad_q28",
    "unpack_biquad_q28",
    "pack_biquad_q31",
    "unpack_biquad_q31",
    # Synthesizer
    "SUPPORTED_SAMPLE_RATES",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_SHELF_F0",
    "DEFAULT_BOOST_GAIN_DB",
    "DEFAULT_SHELF_SLOPE",
    "TARGET_BAND_DEFAULT",
    "ATTENUATION_MIN_REQUIRED_DB",
    "ATTENUATION_MAX_ALLOWED_DB",
    "SUBSONIC_HPF_DEFAULT_F0",
    "SUBSONIC_HPF_DEFAULT_Q",
    "CXD90050_BIQUAD_COUNT",
    "SynthesisResult",
    "create_identity_biquad",
    "calculate_biquad_poles",
    "pad_biquad_cascade",
    "create_alignment_block",
    "synthesize_low_shelf",
    "synthesize_peaking_eq",
    "synthesize_high_pass",
    "synthesize_anc_boost",
    # Stability
    "FilterInstabilityError",
    "PolePair",
    "StabilityMargin",
    "QuantizationStabilityReport",
    "StabilityReport",
    "compute_characteristic_roots",
    "check_schur_cohn",
    "compute_stability_margins",
    "is_biquad_stable",
    "assert_biquad_stable",
    "verify_quantization_invariance",
    "validate_alignment_block_stability",
    # Simulation
    "AttenuationBandViolationError",
    "BandVerificationResult",
    "FrequencyResponse",
    "create_frequency_grid",
    "evaluate_biquad_dtft",
    "evaluate_cascade_dtft",
    "evaluate_alignment_block_dtft",
    "verify_attenuation_band",
    "assert_attenuation_band",
    "render_ascii_response_curve",
]
