# Handoff — WH-1000XM4 ANC Optimizer

Son güncelleme: 2026-10-28

## Proje durumu

Firmware v2.5.0 reverse engineering büyük ölçüde tamamlandı. Cihaz üzerinden NVDM yedekleme,
firmware flash (upgrade/downgrade), ANC modu değiştirme, RAM okuma/yazma çalışıyor.
**Kalıcı ANC katsayı enjeksiyonu henüz çözülmedi.**

## Tamamlanan işler

### Firmware RE
- Ghidra headless ile section 4 (ana ARM firmware, 1.69 MB) tam decompile: **5406 fonksiyon, 217K satır C kodu**
  - Dosya: `~/Desktop/XM4_Firmware_Readable/2.5.0/xm4_firmware_decompiled.c`
  - Ghidra projesi: scratchpad `ghidra_project/xm4_fw` (analiz tamamlanmış, tekrar kullanılabilir)
- RACE dispatch table (`0x08305B7C`): 8 entry tümü haritaya alındı
- Optimizer katsayı pipeline tamamen izlendi:
  - `FUN_082bb468`: NVDM'den oku → CXD90050'ye gönder (boot restore)
  - `FUN_082bb5d8`: Optimizer sonucu → LE→BE swap → CXD90050 + NVDM yaz (optimizer completion handler)
  - İki ayrı RAM buffer: `0x1001A7B8` (heap, NVDM ile eşleşiyor) ve `0x10004058` (struct+0x10, boot sonrası farklı veri)

### RACE protokolü
- Şifreleme/kimlik doğrulama yok (CVE-2025-20700/20701/20702)
- READ_ADDRESS (`0x1680`) ve WRITE_ADDRESS (`0x1681`) çalışıyor
- 0x09xx sub-commands XM4'te cevap vermiyor (0x00–0x3F tümü test edildi)
- PAGE_PROGRAM (`0x0402`) retail firmware'de engellenmiş (`rc=0x0A`)
- NVDM write (`0x0E02`) stub — `00` döner ama yazmıyor

### ATCI (relay mode üzerinden)
- NCOPTSET doğru format: `AT+NCOPTTOOL=NCOPTSET,<offset>,0x<value>` — RAM'e yazıyor, NVDM'e değil
- COEFSET doğru format: `AT+HWPTOOL=COEFSET,<filter>,<stage>,<b0>,...,<a2>` — kabul ediliyor
- Relay mode sınırlaması: yanıt her zaman 3 byte (tam AT çıktısı UART'a gidiyor)

### Power-cycle testleri (3 deneme, hepsi başarısız)
1. Marker yalnızca `0x10004058`'e → NVDM değişmedi
2. Marker `0x10004058` + `optimizer_is_optimized` flag = 1 → NVDM değişmedi
3. Marker HER İKİ buffer'a (`0x10004058` + `0x1001A7B8`) + flag → NVDM değişmedi

Sonuç: Firmware'in power-off save'i ya üçüncü bir buffer'dan okuyor, ya da gerçek optimizer çalışmadığında koşullu olarak atlıyor.

### Emülasyon
- `VirtualXM4Device` power-cycle emülasyonu eklendi (`95274a4`)
- İyimser/kötümser senaryo testleri mevcut

## Çözülmemiş sorunlar

### 1. Kalıcı katsayı enjeksiyonu (ana hedef)
RAM'e yazılan değerler power cycle sonrası NVDM'de görünmüyor. Olası nedenler:
- `FUN_082bb5d8` optimizer completion handler, power-off save değil
- Gerçek power-off batch save fonksiyonu henüz belirlenmedi
- Power-off save koşullu olabilir (gerçek optimizer run olmadan tetiklenmiyor)

### 2. READ_ADDRESS kısıtlaması
Yoğun okuma sonrası `rc=3` hatası — yalnızca `0xXX000000` base adresler çalışıyor. Cihaz yeniden başlatılınca düzelebilir.

## Sonraki adımlar (öncelik sırasıyla)

1. **Decompile çıktısında power-off save zincirini bul**
   - 5406 fonksiyonlu C kodu hazır (`xm4_firmware_decompiled.c`)
   - `FUN_082bb5d8`'i çağıran fonksiyonları takip et
   - `optimizer_coeff` string'inin 3 xref'i dışında `nvdm_write` çağrılarını tara
   - Power-off batch save (volume, ANC mode, optimizer_coeff birlikte yazılıyor) fonksiyonunu bul

2. **Gerçek NC Optimizer çalıştır, sonra power cycle**
   - MDR `84 01 00 01` ile optimizer başlat, tamamlanmasını bekle
   - Optimizer'ın kendi çıktısı NVDM'e yazılıyorsa, o anki RAM buffer'ı yakalayıp değiştir
   - Optimizer tamamlandıktan sonra ama power-off'tan önce buffer'ı değiştir

3. **Doğrudan NVDM flash yazma**
   - Log-structured store'a yeni record append et
   - `storage_type=1` ile PAGE_PROGRAM dene (önceki testler sadece `storage_type=0`)
   - Çalışırsa en temiz çözüm: doğrudan NVDM'e istenen katsayıları yaz

4. **Firmware patching (son çare)**
   - Power-off save fonksiyonunu değiştir: bilinen buffer'dan her zaman kaydet
   - Veya identity-overwrite koşulunu bypass et
   - FOTA flasher çalışıyor, custom image yüklenebilir (imza kontrolü bilinmiyor)

## Dosya haritası

| Dosya | Ne |
|---|---|
| `docs/STATUS.md` | Tüm kanıtların detaylı kaydı |
| `docs/HARDWARE_AND_NVDM.md` | NVDM format belgeleri |
| `docs/WIRE_PROTOCOLS.md` | MDR + RACE protokol belgeleri |
| `xm4_optimizer/transport/virtual_device.py` | Emülatör (power_cycle dahil) |
| `tools/verify_coefset.py` | RAM buffer okuma/yazma testi |
| `tools/post_cycle_verify.py` | Power cycle sonrası doğrulama |
| `tools/backup_nvdm.py` | NVDM yedekleme |
| `tools/flash_firmware.py` | Firmware flasher |
| `~/Desktop/XM4_Firmware_Readable/2.5.0/xm4_firmware_decompiled.c` | Tam decompile (5406 fn) |

## Kritik RAM adresleri

| Adres | İçerik |
|---|---|
| `0x10004048` | CXD90050 NC state struct base |
| `0x100040C8` | → `0x1001A7B8` (heap buffer pointer) |
| `0x1001A7B8` | 40-byte katsayı buffer (BE Q4.28, NVDM ile eşleşiyor) |
| `0x10004058` | struct+0x10, boot sonrası farklı veri içeriyor |
| `0x100798B4` | `optimizer_is_optimized` flag |
| `0x08305B7C` | RACE dispatch table (8 entry) |

## Kısıtlamalar

- Commitlerde AI etiketi yok, kullanıcı kimliği: Ege <randward@proton.me>
- Ham araştırma notları repoya girmez — yalnız derlenmiş özet
- STATUS.md her zaman doğrudur, diğer belgelerle çelişirse STATUS kazanır
