---
sidebar_position: 8
---

# Görev Talepleri ve Gelen Kutusu

## Gelen Kutusu

Gelen Kutusu, size ulaşan her şeyin toplandığı yerdir: **akış sonuçları**, **görev talepleri** ve sistem bildirimleri. Adresi `/inbox`'tur (kenar çubuğunda bağlantısı yoktur; **Kullanıcı** rolündeki kişiler girişte doğrudan buraya yönlendirilir).

- Okunmamış mesajlar rozetle sayılır; liste 30 saniyede bir kendini yeniler.
- Filtreler: **Tümü**, **Bu hafta**, **Bu ay**, **Sadece yeni**.
- Bir mesajı açınca okundu olur; **Tümünü Okundu İşaretle** ve silme düğmeleri vardır. Her kullanıcı yalnızca kendi mesajlarını görür ve siler.

## Görev talebi: doğru ajana iş yönlendirme

Bir işin hangi ajana gideceğini bilmiyorsanız **Görev Talebi** oluşturun; sistem uygun ajanı bulur.

1. Gelen Kutusu'nda **Görev Talebi**'ne basın.
2. **Başlık** ve **Açıklama** yazın (ikisi de zorunlu). İsterseniz bir **departman** ve bir **yetenek filtresi** (ör. `analiz`, `rapor`) verin.
3. Sistem şöyle yönlendirir:
   1. Şirketteki **aktif** ajanları yetenek filtresine göre süzer.
   2. İstenen departmandaki ajanı, yoksa üst departmanlardakini tercih eder (departman verilmediyse tüm şirkette arar).
   3. İlk uygun ajanı atar ve ajanın **sorumlu insanına** bir bildirim gönderir.

Uygun ajan bulunamazsa talep **bekliyor** (`pending`) kalır; bulunursa **atandı** (`assigned`) olur.

## Sorumlu kişinin onayı

Atanan ajanın sorumlusu, Gelen Kutusu'ndaki **Onayınızı Bekleyen Görevler** bölümünde talebi görür:

- **Çalıştır:** Ajan görevi çalıştırır; sonuç canlı akar ve talep **tamamlandı** (`completed`) olur. Bir hata olursa talep tekrar denenebilir duruma döner.
- **Reddet:** İsteğe bağlı bir not yazılır; talep **reddedildi** olur. Notu talebin kaydında görebilirsiniz.

Yalnızca sorumlu kişi çalıştırabilir veya reddedebilir; insan onayı olmadan hiçbir ajan görev üstlenmez. Bekleyen görevleri **Telegram botu** ile de onaylayabilirsiniz (`/onaylar`).

| Durum | Anlamı |
|---|---|
| `pending` | Uygun ajan bulunamadı |
| `assigned` | Ajan atandı, sorumlunun onayı bekleniyor |
| `running` | Çalışıyor |
| `completed` | Bitti, sonuç kayıtlı |
| `rejected` | Sorumlu reddetti |
