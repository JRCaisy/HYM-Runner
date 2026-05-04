# NeedleCrawler Procedural Idle Pipeline
# ========================================
# HY-Motion → Rhythm Extractor → Procedural Composer → FBX
#
# MVP TAMAMLANDI. Bu pipeline şu özellikleri karşılar:
#   ✅ FBX export (Maya + UE5 import eder)
#   ✅ Root motion sıfır (in-place loop)
#   ✅ Ön bacak kompanzasyonu (chest hareketi absorbe edilir)
#   ✅ Loop dikişi (cosine blend)
#   ✅ Breathing + head + tail + ear/leg twitch


# ═══════════════════════════════════════════════════════
# DOSYA YAPISI
# ═══════════════════════════════════════════════════════
#
#   Idle\
#   ├── extract_rhythm.py       ← npz → curves.json
#   ├── compose_idle.py         ← curves + config → FBX
#   ├── validate_config.py      ← config hata kontrolü
#   ├── fbx_writer.py           ← pure-Python FBX writer (hareket ettirme!)
#   ├── README_pipeline.txt     ← bu dosya
#   └── configs\
#       ├── needlecrawler.json  ← NeedleCrawler rig + idle profili
#       └── curves_v08.json     ← HY-Motion energy verisi


# ═══════════════════════════════════════════════════════
# ADIM 1 — Kurulum (bir kerelik)
# ═══════════════════════════════════════════════════════
#
#   pip install numpy scipy matplotlib


# ═══════════════════════════════════════════════════════
# ADIM 2 — HY-Motion'dan idle üret
# ═══════════════════════════════════════════════════════
#
# ComfyUI → HY-Motion Runner ile NPZ üret.
# Önerilen prompt:
#   "A person stands still and waits, looking forward,
#    with very small breathing motion."
# Duration: 150 frame (5 saniye)
# Export NPZ: ON


# ═══════════════════════════════════════════════════════
# ADIM 3 — Energy curve çıkar
# ═══════════════════════════════════════════════════════
#
#   python extract_rhythm.py --input Humanidle_v08.npz --output configs\curves_v08.json --plot rhythm.png
#
# rhythm.png'ye bak:
#   Energy curve'de birden fazla tepe/dip var → iyi sinyal
#   Düz çizgi veya tek büyük tepe → farklı seed/prompt dene


# ═══════════════════════════════════════════════════════
# ADIM 4 — Config doğrula (önerilen)
# ═══════════════════════════════════════════════════════
#
#   python validate_config.py --config configs\needlecrawler.json


# ═══════════════════════════════════════════════════════
# ADIM 5 — FBX üret
# ═══════════════════════════════════════════════════════
#
#   python compose_idle.py ^
#     --config configs\needlecrawler.json ^
#     --energy configs\curves_v08.json ^
#     --output idle_needlecrawler.fbx ^
#     --preview idle_preview.png
#
# idle_preview.png'ye bak:
#   Chest Y pos   → düzgün sin dalgası, başı-sonu yakın (loop)
#   Head yaw      → energy yüksekken amplitüd artıyor
#   Tail          → bone'lar arası faz farkı (dalga)
#   Twitches      → birkaç sparse event
#
# Farklı twitch pattern için seed değiştir:
#   python compose_idle.py ... --seed 123


# ═══════════════════════════════════════════════════════
# ADIM 6 — UE5'e import ve retarget
# ═══════════════════════════════════════════════════════
#
# 6a) FBX'i UE5'e import et:
#     Content Browser → sağ tık → Import to /Game/...
#     idle_needlecrawler.fbx seç
#     Import ayarları:
#       Import Animations: ON
#       Skeleton: yeni oluştur (pipeline skeleton)
#       Import → 
#     Bu "pipeline skeleton" adlı geçici bir skeleton + animasyon asset oluşturur.
#
# 6b) IK Rig oluştur (pipeline skeleton için):
#     Content Browser → sağ tık → Animation → IK Rig
#     Skeleton: pipeline skeleton seç
#     Retarget chain'leri ekle:
#       Spine chain: Hips → chest
#       Head chain: head
#       Tail chain: tail → tail3
#       LeftFrontLeg: frontleg → frontleg2
#       RightFrontLeg: R_frontleg → R_frontleg2
#       LeftHindLeg: backleg → backleg2
#       RightHindLeg: R_backleg → R_backleg2
#
# 6c) NeedleCrawler skeleton için IK Rig oluştur (zaten varsa atla):
#     Aynı chain isimleriyle NeedleCrawler skeleton üzerinde yap.
#     Bone isimleri birebir aynı olduğu için chain mapping otomatik eşleşir.
#
# 6d) IK Retargeter oluştur:
#     sağ tık → Animation → IK Retargeter
#     Source: pipeline skeleton IK Rig
#     Target: NeedleCrawler IK Rig
#     Chain mapping ekranında eşleşmeleri gör (otomatik olmalı)
#
# 6e) Animasyonu export et:
#     IK Retargeter'ı aç → sol panelde idle animasyonu seç
#     Export Selected Animations
#     Hedef: NeedleCrawler'ın animation klasörü
#
# Sonuç: NeedleCrawler'a ait temiz idle animasyon asset'i
# Animation Blueprint'te Idle state'e atanmaya hazır.


# ═══════════════════════════════════════════════════════
# ADIM 7 — Animation Blueprint'e ekle (UE5)
# ═══════════════════════════════════════════════════════
#
# NeedleCrawler'ın Animation Blueprint'ini aç
# State Machine'de Idle state'e:
#   Play Animation → NeedleCrawler_Idle
#   Loop: ON
#   Play Rate: 1.0 (yavaşlatmak istersen 0.8)


# ═══════════════════════════════════════════════════════
# MAYA KULLANIMI (opsiyonel, UE'den önce kontrol için)
# ═══════════════════════════════════════════════════════
#
# File → Import → idle_needlecrawler.fbx
# Import ayarları: Scale 1.0, Y up
# Outliner'da "Hips" skeleton'ı göreceksin
# Play basınca animasyonu gör
#
# NeedleCrawler rig'ine aktarmak için:
#   - BVH skeleton ile NeedleCrawler arasında orient constraint
#   - Bake Simulation → constraint sil
#   - File → Export → FBX → UE'ye import


# ═══════════════════════════════════════════════════════
# PARAMETRE AYARI
# ═══════════════════════════════════════════════════════
#
# configs\needlecrawler.json'da değiştir:
#
#   Nefes çok büyük/küçük:
#     profile.breathing.chest_offset_amplitude_units  (şu an: 1.2)
#
#   Baş çok fazla dönüyor:
#     profile.head_micro_motion.yaw_amplitude_deg  (şu an: 3.0)
#
#   Kuyruk çok sallıyor:
#     profile.tail_secondary_motion.amplitude_deg  (şu an: 5.0)
#
#   Kulak çok sık seğiriyor:
#     profile.ear_twitch.events_per_minute  (şu an: 6)
#
#   Farklı twitch pattern:
#     --seed parametresini değiştir
#
# Değişiklik sonrası ADIM 5'i tekrar çalıştır.


# ═══════════════════════════════════════════════════════
# BAŞKA YARATIK İÇİN KULLANMAK
# ═══════════════════════════════════════════════════════
#
# configs\quadruped_schema.json'u kopyala ve doldur:
#   cp configs\quadruped_schema.json configs\yeni_yaratik.json
#
# Doldurman gerekenler:
#   rig.skeleton.pelvis       → root bone adı
#   rig.skeleton.spine        → spine bone listesi (pelvis'ten chest'e)
#   rig.skeleton.front_legs   → ön bacak bone isimleri
#   rig.skeleton.hind_legs    → arka bacak bone isimleri
#   rig.skeleton.tail         → kuyruk bone listesi
#   profile.breathing.spine_distribution → spine bone sayısıyla aynı uzunlukta
#
# Doğrulama:
#   python validate_config.py --config configs\yeni_yaratik.json
#
# Üretim:
#   python compose_idle.py --config configs\yeni_yaratik.json --output yeni_idle.fbx


# ═══════════════════════════════════════════════════════
# HIZLI REFERANS
# ═══════════════════════════════════════════════════════
#
# Kurulum (bir kerelik):
#   pip install numpy scipy matplotlib
#
# Energy çıkar:
#   python extract_rhythm.py --input motion.npz --output configs\curves.json --plot rhythm.png
#
# Config doğrula:
#   python validate_config.py --config configs\needlecrawler.json
#
# FBX üret:
#   python compose_idle.py --config configs\needlecrawler.json --energy configs\curves_v08.json --output idle_needlecrawler.fbx --preview idle_preview.png
#
# Farklı seed:
#   python compose_idle.py ... --seed 789
#
# BVH üret (gerekirse):
#   python compose_idle.py ... --output idle.bvh
