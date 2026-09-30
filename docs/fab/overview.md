---
sidebar_position: 1
---

# Departman Çalışma Alanı (fab) — Genel Bakış

**fab**, her departmanın (finans, muhasebe, satış…) terminalden çalıştığı istemcidir. Rust + Ratatui ile yazılmış tek bir ikili dosyadır. Kişi giriş yapar; kendisine ait, sunucuda çalışan bir **çalışma alanına** bağlanır ve orada **tek bir ajanla** çalışır. Ajan belgeleri, tabloları ve sunumları üretir; şirketin araçlarına politika ve denetim altında erişir.

> Geliştiriciler için olan [Ajan Yürütme Katmanı](/docs/workstation/overview) (opencode + laptop sandbox) yerinde durur. `fab`, aynı gateway, politika motoru ve denetim zincirini kullanan ikinci yoldur. Web arayüzü bu yüzden değişmez.

## Ne var, ne yok

| Parça | Durum |
|---|---|
| `fab` istemcisi: giriş, kenar çubuğu, yerel ajan paneli, `fab workspace`, `fab sync` | Çalışıyor, testli |
| Çalışma alanı API'si (oluştur, sürdür, askıya al, dosyalar, bağlanma bileti) | Çalışıyor, testli |
| Kişi başına tek ajan, token bütçeli prompt birleştirme, niyet sınıflandırma | Çalışıyor, testli |
| **İş incelemem** (`v`), puanlar ve itiraz, eğitim sinyali | Çalışıyor, şirket başına **kapalı** gelir |
| Kalibrasyon aracı, rubrik denetleyicisi (linter), örneklemeli puanlama | Çalışıyor; canlı Jev ile **ölçülmedi** |
| Çalışma alanı imajı (LibreOffice, PDF araçları, headless Chromium) | İlk sürüm; Docker'da **çalıştırılmadı** |
| **Gerçek çalışma alanı çalışma zamanı** | **Yok** — yalnızca test için `FakeRuntime` |

Bu yüzden bugün `fab` gerçek bir müşteride kullanıma hazır değildir: sunucu tarafında gerçek bir çalışma alanı çalışma zamanı yoktur ve uygunluk puanlaması canlı Jev API'siyle ölçülmemiş, hukuki incelemeden geçmemiştir. Ayrıntı için [Yönetici Rehberi](/docs/fab/enablement).

## Ekran

```
┌─ Şirket ────────────────────┬──────────────────────────────────────────┐
│ ▸ Finans › Muhasebe         │                                          │
│   Rol: Borç Uzmanı          │   ajan oturumu                           │
│   Bağlı olduğu: A. Yılmaz   │                                          │
├─ Tekrarlayanlar ────────────┤                                          │
│ ● 09:00 Günlük nakit raporu │                                          │
├─ Son çalıştırmalar ─────────┤                                          │
│ ✓ 09:00 Günlük nakit raporu ├──────────────────────────────────────────┤
│ ⧗ onay: PO #4411            │ dosyalar: nakit-2026-09-28.xlsx          │
└─────────────────────────────┴──────────────────────────────────────────┘
```

Kenar çubuğu mevcut API'lerden beslenir (organizasyon ağacı, akışlar, gelen kutusu, onaylar). Klavye öncelikli; alt satırda tuş ipuçları görünür.

## Bölümler

- [Çalışma alanı ve senkronizasyon](/docs/fab/workspace) — yaşam döngüsü, bağlanma, yerel klasör
- [Kişinin ajanı ve prompt](/docs/fab/agent-and-context) — tek ajan, "Alanım", token bütçesi, niyet sınıflandırma
- [İş incelemesi](/docs/fab/work-review) — ne toplanır, ne toplanmaz, kim ne görür
- [Uygunluk rubriği](/docs/fab/fit-rubric) — puanlama, kalibrasyon, gölge dönem, eğitim sinyali
- [Yönetici rehberi](/docs/fab/enablement) — anahtarlar, ön koşullar, doğrulama, bilinen sınırlar

Mimari kararların tamamı `agentic-organization` deposunda `docs/adr/` altındadır (ADR-0014, 0018–0021). Bu ADR'ler henüz `proposed` durumundadır.
