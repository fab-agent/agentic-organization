---
sidebar_position: 4
---

# İzleme

> ADR-0034 · ADR-0035 · ADR-0038 (önerildi)

`GET /admin/monitoring?company_id=[&deep=true]` tek şirket için tek bakışta durum verir. Yalnızca o şirketin
**şirket genelindeki kurucu veya yöneticisi** görebilir (anonim 401, üye değilse 404, rol yoksa 403; departmana
bağlı yönetici de 403). Aynı görünüm web arayüzünde `/monitoring` sayfasındadır.

Her bölümün durumu `ok`, `warn`, `fail` veya `unknown` olur; genel durum en kötüsüdür. Bir bölüm hata verirse
yanıtı bozmaz, `unknown / section_failed` döner ve ayrıntı yalnızca sunucu günlüğüne gider.

| Bölüm | Ne gösterir |
|---|---|
| `service` | Sürüm, veritabanına erişim |
| `audit` | Olay sayısı ve dış çapa durumu; zincirin tamamı yalnızca `deep=true` ile yeniden hash'lenir (aksi halde `verified: null`) |
| `gateway` | Bugün ve bu ay istek/token, en çok kullanan ajanlar; yalnızca *kaydedilmiş şirket kimliği* eşleşen satırlar |
| `eval` | Son 30 günün tanıları; hipotezdir, hata oranı değil |
| `workspace` | İmza malzemesi yükleniyor mu, epoch, CRL numarası, sertifikada kalan gün (14 günün altı `warn`) |
| `sessions` | Son 5 dakikada canlı oturumlar; kaçının politikası hazır, kaçı hazır değil |
| `clients` | İstemcilerin **kendi bildirdiği** sapma; kimse raporlamadıysa `unknown` |

### "Canlı" ile "politika hazır" aynı şey değildir

`3pa run` çalışırken yaklaşık 30 saniyede bir nabız gönderir. Sunucu nabzı **her zaman** kaydeder ve yanıta
`policy_ready`, `policy_reason` (sabit kodlar: `scope_unreadable`, `invalid_mode`, `invalid_default_effect`,
`policy_unreadable`, `policy_malformed`) ve `policy_mode` ekler. "Hazır değil", *politika bozuk ve çağrılar
reddedilebilir* demektir; her çağrının reddedildiği anlamına gelmez. `3pa run` durum değişince tek satır yazar,
sandbox'ı durdurmaz. Hazır olma bilgisi sunucunun *o an çözebildiğidir*; makinenin veya yerel opencode'un
politikaya uyduğunu kanıtlamaz.

### Bu sayfanın yapmadığı

Zaman serisi, uyarı, çalışma süresi yoklaması, günlük araması, şirketler arası görünüm yoktur. `clients`
bölümü ölçüm değil kendi beyandır.
