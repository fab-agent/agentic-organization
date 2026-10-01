---
sidebar_position: 4
---

# Güvenlik

Bu sayfa web platformunun güvenlik özelliklerini ve **bilinen sınırlarını** açıkça anlatır. Geliştirici iş istasyonu katmanının (gateway, politika motoru, denetim zinciri) güvenliği ayrıdır: [Geliştirici İş İstasyonu](/workstation/overview).

## Kimlik doğrulama

- **Davet tabanlı:** kendi kendine kayıt yoktur. Yalnızca veritabanı boşken ilk kurulum sayfası çalışır.
- **Şifreler** bcrypt ile özetlenir. Geçici şifre 30 dakika geçerlidir ve ilk girişte değiştirilmek zorundadır.
- **Oturum** JWT (HS256) ile yapılır; token ömrü 72 saattir. `ENVIRONMENT=production` iken zayıf veya yer tutucu `JWT_SECRET` ile uygulama **başlamayı reddeder**.
- **Demo kiracısı:** parolasız, e-postaya tek kullanımlık 6 haneli kod (15 dk, dakikada bir sınır). Yalnızca `demo` şirketinde yönetici rolü verir.
- Nginx giriş sayfasına hız sınırı uygular.

## Gizli verilerin saklanması

Sağlayıcı anahtarları, Git ve Telegram token'ları, yedekleme gizli anahtarı ve veritabanı bağlantı dizeleri **Fernet** ile şifrelenerek saklanır; API'ler bunları geri döndürmez. Şifreleme anahtarı `data/.secret` dosyasındadır (ilk çalışmada otomatik üretilir, izin `600`). **Bu dosya veritabanı yedeğiyle birlikte saklanmalıdır**; kaybolursa şifreli kayıtlar çözülemez.

:::note
`.env.example` içindeki `ENCRYPTION_KEY` değişkeni kod tarafından okunmaz; şifreleme anahtarını belirlemez.
:::

## Yetkilendirme: bilinmesi gerekenler

- **Şirket yalıtımı:** şirkete bağlı veriler için kullanıcının o şirketin üyesi olması gerekir.
- **Rol kontrolü kısmen arayüzdedir.** Arayüz menüleri ve düğmeleri role göre gizler; API'de ise departman, personel, akış, ajan gibi birçok işlem yalnızca şirket üyeliğini kontrol eder. API'de rol zorunlu olanlar: şirket bilgisi güncelleme (yönetici+), şirket silme ve kullanıcı/Telegram yönetimi (kurucu), `require_manager` ile korunan işlemler (sağlayıcı anahtarları, politika/yetenek yazma, yedek, veritabanı bağlantıları, politika motoru kipi). `require_manager`, kullanıcının **herhangi bir şirkette** en az bölüm yöneticisi olmasını arar, o şirkette değil.
- Sonuç: düşük yetkili bir üyenin API'yi doğrudan çağırarak arayüzde göremediği bazı işlemleri yapması mümkündür. Hassas ortamlarda API'ye erişimi ağ düzeyinde kısıtlayın ve bunu [Geliştirici Notları](/developer-notes/known-limits)'ndaki iyileştirme listesinde takip edin.

## Ajan eylemlerinin sınırlanması

- Her araç çağrısı politika motorundan geçer (`dry_run` varsayılan; `enforce` ile zorlanır). Bkz. [Politika Motoru](/workstation/policy-engine).
- Veritabanı yeteneği yalnızca `SELECT` çalıştırır; yine de salt okunur bir veritabanı kullanıcısı verin.
- `function` yeteneği tam izole değildir ([Yetenek Türleri](/technical/skill-types#function)).
- Ajan değişiklikleri (yapılandırma, yetenek, politika) iki aşamalı onaydan geçer ve her ikisi de denetim kaydına yazılır.
- Ajanlar arası görev devri iki insan onayı ister.

## CORS ve ağ

İzinli kaynaklar `CORS_ORIGINS` veya `APP_URL`'den gelir; kimlik bilgisiyle birlikte `*` kullanılmaz. Üretimde yalnızca 80/443 dışarıya açık olmalıdır.
