# WH-1000XM4 firmware comparison: what the device data shows

Date: 2026-10-26. One WH-1000XM4 was tested through a 2.5.0 → 3.0.1 → 2.5.0 firmware cycle. This is a comparison of firmware images and stored device data, **not** a measurement of acoustic noise reduction.

## Device test

The headset started on 2.5.0 with 80% battery and noise cancelling selected. Automatic power off was temporarily disabled for the transfer. The two official image files were identified by their SHA-256 digests before flashing. The corrected flasher used the FOTA partition returned by `0x1C00`: storage type `1`, base `0x00510000`, length `0x005FF000`.

| Step | Firmware reported over Sony MDR after power-on | 512 KiB NVDM backup SHA-256 | Valid PEBs / active items / corrupted items |
|---|---|---|---|
| Before upgrade | 2.5.0 | `e27b654836012074498b93aad4da498be3ee2ce03e4c32904ec3b2bc283e9f13` | 128 / 230 / 0 |
| After upgrade | 3.0.1 | `3c6a12942f8b48e2989a73d0265b66e93a1639294febffdd5a6b5478b401747e` | 128 / 230 / 0 |
| After downgrade | 2.5.0 | `c0b50b7af88a915f11feeae034456a5478eb1ecb962f7e6418297f61dab0ba98` | 128 / 230 / 0 |

The 3.0.1 flash staged 16,219 pages; the return to 2.5.0 staged 5,452. The device accepted `0x1C01` (integrity check) and `0x1C02` (commit) in both directions. The firmware version was read from the headset after each manual power-on. The headset returned to 2.5.0, 80% battery, and noise cancelling. The original automatic-power-off setting was restored and confirmed by readback.

Nine active NVDM values differed between the first two backups. Their names concern pairing, boot, power, capability and port-service state. Seven values of interest to the old ANC claim were **byte-identical in all three backups**: `config/optimizer_coeff`, `config/nc_is_optimized`, `config/nc_atm_value`, and `CXD90050/ALIGN_FF_L`, `ALIGN_FF_R`, `ALIGN_FB_L`, `ALIGN_FB_R`. The complete dumps are kept privately because NVDM contains paired-device data.

## Offline firmware image comparison

The official image SHA-256 digests are `ee2a4b60c5f322d56fd9e6ea51778cbbc847f816781c385f40d45959555ac508` (2.5.0) and `2c82f6e5467722d2ea990805b001694704eea4b54ee36e8d38200b761b5c6f75` (3.0.1). The AES-128-CBC key and IV published by [sony-vp-extract](https://github.com/HelgeSverre/sony-vp-extract) decrypted both image bodies. Both decrypted streams decompressed as LZMA. The 7 and 8 decompressed section hashes, respectively, matched the SHA-256 digests in each image's FOTA header. The TLV/section layout follows [airoha-firmware-parser](https://github.com/ramikg/airoha-firmware-parser/blob/main/AirohaFirmware.bt).

| Destination | 2.5.0 section | 3.0.1 section | Byte comparison |
|---|---:|---:|---|
| `0x00012000` | 49,152 B | 49,152 B | Different |
| `0x00032000` | 90,112 B | 90,112 B | Identical |
| `0x000B2000` | 704,512 B | 704,512 B | Different |
| `0x00161000` | 65,536 B | 65,536 B | Different |
| `0x001B9000` | 1,691,648 B | 1,695,744 B | Different |
| `0x0C080000` | Absent | 3,145,728 B | Added in 3.0.1 |
| `0x0C480000` | 32,768 B | 32,768 B | Identical |
| `0x0C490000` | 122,880 B | 122,880 B | Different |

These are section addresses from the firmware metadata. The changed sections have not been mapped to specific ANC routines or coefficient tables. A changed firmware section does not establish that ANC attenuation changed.

## Conclusion and next evidence needed

This test does not support the earlier claim that Sony reduced ANC by 4–6 dB after 2.5.0, nor the proposed reason for such a change. The NVDM values named in that claim did not change on this unit. A firmware change outside NVDM remains possible. To establish a performance difference, measure sound pressure at an ear simulator with the same headset, fit, noise field, ANC setting and battery condition on both firmware versions, with repeated on/off trials and uncertainty estimates. [IEC 60268-24:2023](https://webstore.iec.ch/en/publication/67683) covers headphone active-noise-cancelling measurements. Only after a reproducible acoustic difference is observed should changed code or tables be used to investigate its cause.
