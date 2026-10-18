---
sidebar_position: 9
---

# Ajanlar Arası Delegasyon (A2A)

Bir ajan, kendi yapamadığı bir işi **başka bir ajana** devredebilir. Her devir, ilgili insanların iki kez onayından geçer. Böylece bir ajan, insan görmeden başka bir ajanı çalıştıramaz.

## Akış

```
Ajan A, delegate_to_agent aracını çağırır
        ↓
  pending_approval   → Hedef ajanın sorumlusu görevi onaylar
        ↓
     running         → Hedef ajan görevi çalıştırır
        ↓
  pending_result_approval → Sorumlu sonucu onaylar
        ↓
    completed        → Sonuç, Ajan A'nın oturumuna rapor olarak döner
```

Herhangi bir aşamada **reddedilebilir** (`rejected`); ret nedeni kaydedilir.

Birden fazla ajana paralel devredilirse (ör. bir orkestratör ajanın uzmanlara iş dağıtması), tüm sonuçlar tamamlandığında tek bir **yönetici raporu** olarak derlenir ve başlatan oturuma yazılır.

## Kurulum

1. Görevi devredecek ajana **Ajan delegasyonu** (`delegate_to_agent`) yeteneğini ekleyin ([Yetenekler](/guide/skills-and-policies)). İsterseniz yeteneğin ayarında hedef ajanı sabitleyebilirsiniz.
2. Ajanın talimatına (iş tanımı veya politika) hangi işi hangi ajana devredeceğini yazın. Hedef ajan, **slug**'ı ile adreslenir (**Yapı → Ajanlar**'da görünür).

## Delegasyon sayfası

**Delegasyon** (`/a2a`) sayfası, şirketteki devirleri listeler. Kenar çubuğundaki rozet, onay bekleyen devir sayısını gösterir.

| Sekme | İçerik |
|---|---|
| **Bekleyen** | Onay bekleyenler |
| **Tümü** | Geçmiş dahil hepsi |

Her kartta görev, bağlam, (varsa) sonuç ve onaylayan görünür. Düğmeler duruma göre değişir:

- **Görevi Onayla & Çalıştır** → görev başlar.
- **Sonucu Onayla** → sonuç talep eden oturuma döner. Hedef ajan görevi bitirince sonuç **onay bekler**; onaylanana kadar sohbete düşmez.
- **Reddet** / **Sonucu Reddet**.

Onaylayabilecek kişi, hedef ajanın **sorumlu insanıdır**; başkası onaylamaya çalışırsa sistem reddeder. Bekleyen devirleri **Telegram botu** üzerinden de görüp onaylayabilirsiniz (`/onaylar` komutu; bkz. [Ayarlar → Entegrasyonlar](/guide/settings#entegrasyonlar)).

:::note
Delegasyon talepleri şu an Gelen Kutusu'na mesaj düşürmez. Bekleyen işleri Delegasyon sayfasından, rozetten veya Telegram'dan izleyin.
:::
