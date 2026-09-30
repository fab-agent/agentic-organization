---
sidebar_position: 5
---

# Uygunluk Rubriği ve Puanlama

Bir işin şirketin hedef, değer ve politikalarına **uygunluğu**, tiplenmiş evet/hayır soruları ve olasılıkla ölçülür (ADR-0021). Serbest metinli not değil; bir sınıflandırıcı (TypeSafe Jev `Noul`) olasılık döndürür.

> **Durum:** çalışıyor ve testli, ancak canlı Jev API'siyle ölçülmedi ve hukuki incelemeden geçmedi. Bu yüzden şirket başına **kapalı** gelir.

## Ölçüt (criterion)

Bir ölçüt, **iş hakkında** tek bir evet/hayır sorusudur; kişi veya özellik hakkında asla.

| Alan | Anlamı |
|---|---|
| `id` | Kalıcı kimlik (`G2-recurring-revenue`), yeniden kullanılmaz |
| `question` | Tek fikirli kapalı soru |
| `good_answer` | `yes` ya da `no` (politika soruları "hayır" istenebilir) |
| `source` | `{kind, ref, quote}` — şirketin yazdığı kaynak metnin **birebir alıntısı**. Alıntısız ölçüt geçersizdir |
| `scope` | Şirket geneli veya departmanlar |
| `applies_when` | Görev, hassasiyet ve alan etiketlerine göre filtre; uyuşmazsa iş **uygulanamaz** sayılır |
| `thresholds` | `{met: 0.7, not_met: 0.3}` (öneri) |
| `status` | `draft` → `shadow` → `live`, sonra `retired` |

## Puan ne demektir

Olasılık bir **karara** çevrilir: `met`, `not_met` veya `unclear`. `unclear` birinci sınıf bir sonuçtur ve hiçbir tarafa yuvarlanmaz. **Kişi başına puan ve genel not yoktur;** görünümler ölçüt başına sayıları (met / not met / unclear / uygulanamaz) gösterir. Jev metin üretmez, bu yüzden puan satırında serbest metin gerekçe de yoktur (bu aynı zamanda kişisel veriyi satırlardan uzak tutar).

Puanlama **örneklemelidir** (öneri: çalıştırmaların %20'si; kişisel veri sınıfına dokunan her çalıştırma) ve süzülmüş özet üzerinde çalışır.

## Hiçbir şey test edilmeden canlıya çıkmaz

1. **Kalibrasyon.** Yazar ölçüt başına etiketli örnekler yazar. Model kararlarının etiketlerle uyumu en az %85 (belirsiz en çok %30) olmalı; en az 20 örnek, her sınıftan 5. Sonuç ölçütün **tam ifadesi** için kaydedilir; yeniden yazmak kalibrasyona geri gönderir.
2. **Gölge dönem** (öneri: 14 gün). Puanlar hesaplanır ama **yalnızca ilgili kişiye** gösterilir; yönetici görünümü, toplam ve eğitim sinyali yoktur.
3. **Canlı.** Açık onay gerekir.

`set_rubric` bu kapıları zorunlu kılar: kalibrasyonu geçmemiş `shadow`/`live` ölçüt veya 14 gün gölgede kalmamış `live` ölçüt reddedilir. Bugün `shadow → live` geçişi rubrik dosyasında elle yapılır.

Kalibrasyon komut satırından çalışır:

```bash
cd backend
TYPESAFE_API_KEY=... python scripts/calibrate_rubric.py \
  --company <id> --samples samples.yaml [--save]
```

Rapor uyum oranını, belirsiz payını, sınıf sayılarını ve örnek başına kararları verir; metinleri asla.

## Sürümleme

Ölçütün kimliği `(id, soru + good_answer + eşiklerin özeti)`'dir. Eski puanlar eski sürümle kalır, sessizce yeniden puanlanmaz; toplamlar sürümleri karıştırmaz.

## İtiraz

Kişi bir puana notla (≤ 1000 karakter) itiraz eder (`c`). İtirazlı puan; yönetici görünümünden, tüm toplamlardan ve eğitim sinyallerinden çıkar. Çözümü **departman başkanı / yönetici / kurucu** yapar; kişinin kendisi veya doğrudan yöneticisi yapamaz. Her itiraz, geri çekme ve çözüm denetlenir (not metni olmadan).

## Eğitim ihtiyacı sinyali

Önce **birimde** okunur: bir birimde çok kişi aynı ölçütte `not_met` ise bulgu "bu kural veya eğitimi belirsiz" olur ve rubrik sahibine gider (departman başkanı, yönetici, kurucu). Yalnızca `live`, itirazsız, karar verilmiş puanlar sayılır (son 30 gün), en az 10 puan, `not_met` payı çubuğun (öneri %50) üstünde ve grup tabanı (3) sağlanmalı.

**Kişinin sinyali yalnızca kendi ekranında görünür.** İsterse doğrudan yöneticisiyle paylaşır (`t`, `s`, `y`); paylaşım ölçüt bazlı rızadır, veri kopyası değildir ve geri çekilebilir. Şirketin önce `sharing_enabled` açması gerekir; bu, hukuki inceleme bitene kadar **kapalıdır**. Takım liderleri yalnızca kendi takımlarının birim bulgusunu (yalnızca sayılar) görür.

## Henüz yok

- Rubrik `AppConfig` satırında durur; politika deposuna ve değişiklik talebi akışına taşınmadı.
- `fab`'ta rubrik görünümü, birim bulguları ve itirazı çözen kişi ekranları yok (API'ler hazır).
- Kalibrasyonun API'si veya ekranı yok, yalnızca komut satırı.
- Tüm eşikler (%85, %30, 20, 14 gün, %20, 10, %50, 3) **öneridir, ölçülmemiştir.**
