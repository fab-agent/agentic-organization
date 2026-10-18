---
sidebar_position: 4
---

# İş İncelemesi

Her çalıştırma ve oturum tek bir hattan geçer (ADR-0019 §6). Hat, ADR-0013'teki risk puanlamasını genişletir; ikinci bir sistem değildir. **Şirket başına kapalı gelir**, kurucu açar.

## Hat

1. **Süz.** Depolanmadan veya puanlama modeline gitmeden önce hassas içerik sınıflandırılır ve maskelenir.
2. **Etiketle.** Departman, konu, veri sınıfı, eylem türleri (okuma/yazma/gönderme/harcama), kullanılan araç.
3. **Uygunluğu puanla.** Şirketin kendi ölçütlerine göre (bkz. [Uygunluk rubriği](/fab/fit-rubric)).
4. **Yönlendir.** Risk eşiği aşılırsa gelen kutusu/uyarı; tekrarlayan düşük sonuçlar **eğitim ihtiyacı** sinyali olur.

Puanlar ve etiketler, denetim sıra numaralarına bağlı yan tablolardır. **Denetim zinciri asla değiştirilmez.**

## Ne toplanır, ne hiç toplanmaz

Toplanan: çalıştırma/oturum özetleri (süzülmüş), etiketler, politika reddi ve onay sayıları, kişinin ajan çıktısını düzeltme sayısı.

**Hiç toplanmaz:** tuş vuruşu, ekranda geçirilen süre, devam/devamsızlık, ekran görüntüsü. Kapalıysa `fab` "hakkınızda hiçbir şey toplanmıyor" der.

## Kim ne görür

| Görüntüleyen | Gördüğü |
|---|---|
| Kişinin kendisi | Kendi puanları, sinyalleri, ayrıntıları — hepsi |
| Doğrudan yönetici | Bağlı kişiler için kişi bazlı sonuçlar (yalnızca yürürlükteki, itirazsız) |
| Bir üst yönetici | Yalnızca takım/bölüm toplamları |
| Daha üstü | Yalnızca departman toplamları |

Kurallar: kişi, yöneticinin gördüğünden **daha fazlasını** görür, asla azını; gizli puan yoktur. Küçük gruplar toplam olarak gösterilmez (asgari grup büyüklüğü, `WORK_REVIEW_MIN_GROUP`, varsayılan 3). Kişi kendi notlarını ekleyebilir ve silebilir. **Puanlar hiçbir istihdam kararının tek dayanağı olamaz** (KVKK/GDPR profilleme sınırları).

## `fab` içinde: "İş incelemem" (`v`)

Toplamlar, günler, ne toplanıp ne toplanmadığı, kimin gördüğü ve kişinin kendi notları. Puanlar için `c` itiraz eder, `u` geri çeker. Eğitim sinyali için `t` seçer, `s` paylaşmayı sorar, `y` onaylar, tekrar `s` geri çeker.

## Zamanlayıcı işleri

| İş | Sıklık |
|---|---|
| `work_review_rollup` | saatlik |
| `work_review_purge` | günlük |
| `work_rating` | saatlik |

Saklama süresi varsayılan **365 gün**; kişi silinince satırları da silinir.

## Bilinen sınır: süzme yalnızca biçime bakar

Süzme e-posta, URL, kart, IBAN, T.C. kimlik, telefon, IP ve gizli anahtarları maskeler. **İsimleri, adresleri ve düz yazıdaki ayrıntıları tanımaz.** Bu bir tabandır: özet hâlâ puanlama sağlayıcısına (Jev) gider. Bu yüzden hukuki inceleme şarttır.
