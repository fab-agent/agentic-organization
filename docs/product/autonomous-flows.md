---
id: autonomous-flows
title: Otonom Akışlar
sidebar_label: Otonom Akışlar
---

# Otonom Akışlar

Otonom Akışlar, bir ajana cron zamanlayıcısıyla otomatik görev atayan yapılandırmalardır. Belirlenen programda ajan LLM API aracılığıyla görevi çalıştırır; sonuç **Gelen Kutusu**'na düşer.

---

## Kullanım Senaryoları

- Her sabah satış rakamlarını özetleyen günlük raporlar
- Hafta içi her sabah müşteri destek kuyruğunu tarayan ajan
- Saatte bir çalışan sistem sağlık kontrolleri
- Her Pazartesi ekip için haftalık öncelik önerisi üreten ajan

---

## Akış Oluşturma

**Otonom Akışlar** (`/flows`) sayfasına gidin ve **Yeni Akış** butonuna tıklayın.

### Form Alanları

| Alan | Zorunlu | Açıklama |
|---|---|---|
| **Akış Adı** | Evet | Akışı tanımlayan kısa başlık |
| **Ajan** | Evet | Görevi çalıştıracak ajan (yalnızca `agent` türündeki personel listelenir) |
| **Program** | Evet | Cron ifadesi — zamanlama kuralı |
| **Görev Promptu** | Evet | Ajana gönderilecek görev açıklaması |
| **Açıklama** | Hayır | Akışın amacını anlatan serbest metin |
| **Etkin** | — | Akışı aktif/pasif yapar |

### Program — Cron Formatı

```
dakika  saat  gün-ay  ay  haftanın-günü
  0      9     *      *      1-5
```

Yukarıdaki örnek **hafta içi her sabah 09:00**'da çalışır.

Hazır şablonlar:

| Şablon | Cron |
|---|---|
| Her gün 09:00 | `0 9 * * *` |
| Hafta içi 09:00 | `0 9 * * 1-5` |
| Her Pazartesi 08:00 | `0 8 * * 1` |
| Her saat başı | `0 * * * *` |

Özel bir cron ifadesi yazmak için **Özel** seçeneğini seçin ve alanı doğrudan düzenleyin.

---

## Akış Yönetimi

### Etkinleştirme / Devre Dışı Bırakma

Listedeki **Aktif / Pasif** düğmesine tıklayarak akışı anında etkinleştirebilir veya devre dışı bırakabilirsiniz. Pasif akışlar programda çalışmaz, ancak kaydı korunur.

### Şimdi Çalıştır

Her satırdaki **Oynat** ikonuna tıklayarak akışı programdan bağımsız olarak anında çalıştırabilirsiniz. Bu özellik test amacıyla kullanışlıdır. Çalışma tamamlandığında sonuç Gelen Kutusu'na düşer.

### Düzenle / Sil

- **Düzenle** butonu (kalem ikonu) akış formunu tekrar açar; tüm alanlar düzenlenebilir.
- **Sil** butonu onay diyaloğu gösterdikten sonra akışı kalıcı olarak siler.

---

## Çalışma Günlüğü

Her akışın **Son Çalışma** bilgisi tabloda görünür. Çalışma başarısız olduysa `Hata` etiketi gösterilir. Hata detayları Gelen Kutusu'ndaki ilgili mesajda yer alır.

| Sütun | Açıklama |
|---|---|
| Akış | Ad ve açıklama |
| Ajan | Görevi çalıştıran ajan |
| Program | Cron ifadesi |
| Son Çalışma | Son başarılı veya başarısız çalışma zamanı |
| Durum | Aktif / Pasif |

---

## Gelen Kutusu ile İlişki

Her başarılı veya başarısız çalışma, Gelen Kutusu'nda **Akış** etiketli bir mesaj oluşturur. Mesajda:

- Akış adı ve hangi ajan tarafından çalıştırıldığı
- LLM'in ürettiği yanıt (görev çıktısı)
- Çalışma zamanı

Gelen Kutusu ayrıntıları için → [Gelen Kutusu](./inbox.md)

---

## API Endpoint'leri

| Endpoint | Yöntem | Açıklama | İzin |
|---|---|---|---|
| `/flows?company_id=` | GET | Akış listesi | `agent_owner+` |
| `/flows` | POST | Yeni akış oluştur | `agent_owner+` |
| `/flows/{id}` | PUT | Akış güncelle | `agent_owner+` |
| `/flows/{id}` | DELETE | Akış sil | `agent_owner+` |
| `/flows/{id}/run` | POST | Anında çalıştır | `agent_owner+` |
