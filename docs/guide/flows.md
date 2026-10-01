---
sidebar_position: 7
---

# Otonom Akışlar

Akış, bir ajanın **belirli saatlerde kendiliğinden** çalıştığı zamanlanmış görevdir. Sonuç, ajanın sorumlusunun **Gelen Kutusu**'na düşer. Örnekler: her sabah nakit raporu, haftalık tedarikçi özeti, saatlik haber taraması.

**Nerede:** **Akışlar** (Ajan sorumlusu ve üstü).

## Akış oluşturma

**Yeni Akış** ile şunları girersiniz:

| Alan | Açıklama |
|---|---|
| Akış adı | Zorunlu |
| Ajan | Çalışacak ajan; zorunlu |
| Program | **Cron** biçiminde 5 alan: `dakika saat gün ay haftanın-günü`; zorunlu |
| Açıklama | İsteğe bağlı |
| Görev promptu | Ajana her çalışmada verilecek talimat; zorunlu |
| Etkinleştir | Kapalıysa zamanlanmaz |

Cron örnekleri:

| İfade | Anlamı |
|---|---|
| `0 9 * * 1-5` | Hafta içi her gün 09:00 |
| `*/15 * * * *` | Her 15 dakikada |
| `0 8 * * 1` | Her pazartesi 08:00 |

:::caution Saat dilimi: UTC
Zamanlayıcı **UTC** ile çalışır. Türkiye saatiyle (UTC+3) 09:00 için `0 6 * * *` yazın.
:::

## Yönetme

Akış listesi son çalışma zamanını ve durumunu (başarılı / hata) gösterir. **Şimdi Çalıştır** zamanlamayı beklemeden bir kez çalıştırır. Akışı düzenleyebilir, pasif yapabilir veya silebilirsiniz. Değişiklikler zamanlayıcıya kısa sürede yansır.

## Çıktı nereye gider?

- **Gelen Kutusu:** ajanın sorumlusuna bir mesaj (bulunamazsa şirketin bir yöneticisine). → [Görev Talepleri ve Gelen Kutusu](/guide/tasks-and-inbox)
- **Telegram:** şirket için bot tanımlıysa özet oraya da gönderilir. → [Ayarlar → Entegrasyonlar](/guide/settings#entegrasyonlar)
- Akış kaydı son çıktının ilk kısmını (500 karakter) ve hata mesajını saklar.

## Akışlarda araç kullanımı

Akış, ajanın yeteneklerini (ör. web arama) kullanabilir; ancak şu an **araç çağırma yalnızca Anthropic protokollü modellerde** desteklenir. Diğer modellerde akış, araç kullanmadan yalnızca metin üretir. Bir turda en çok 8 araç adımı yapılır.

Görsel üreten modeller (ör. Qwen Image, DALL-E ve uyumlular) seçildiyse akış görsel üretir.

## Birden çok sunucu

Birden fazla çalışan işlem (worker) olsa bile zamanlanmış akışları yalnızca **bir** işlem çalıştırır (bir kilit dosyasıyla); bu yüzden bir akış iki kez tetiklenmez.
