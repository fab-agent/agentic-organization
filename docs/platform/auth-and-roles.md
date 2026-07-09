---
id: auth-and-roles
title: Kimlik Doğrulama ve Roller
sidebar_label: Kimlik Doğrulama ve Roller
---

# Kimlik Doğrulama ve Roller

fab.engineering, davet tabanlı bir kimlik doğrulama sistemi kullanır. Kullanıcılar sisteme kendi kendine kayıt olamaz. Tüm hesaplar, yetkili yöneticiler tarafından oluşturulur ve platforma e-posta daveti ile gönderilir.

---

## Giriş Akışı

### Normal Giriş

1. Kullanıcı `/login` sayfasına gider.
2. E-posta adresini ve şifresini girer.
3. **"Giriş Yap"** butonuna basar.
4. Başarılı girişte ana sayfaya yönlendirilir; sol kenar çubuğu kullanıcının rolüne göre şekillenir.

### İlk Giriş (Geçici Şifre ile)

Yeni davet alan veya şifresi sıfırlanan kullanıcılar geçici bir şifreyle giriş yapar:

1. Kullanıcı `/login` sayfasına gider, e-posta ve geçici şifresini girer.
2. Sistem şifrenin `force_change` işaretli olduğunu tespit eder.
3. Kullanıcı otomatik olarak `/set-password` sayfasına yönlendirilir.
4. Kullanıcı yeni kalıcı şifresini iki kez girer.
5. Şifre kaydedilir; kullanıcı ana sayfaya yönlendirilir.

:::caution
Geçici şifre **30 dakika** geçerlidir. Süre dolduğunda kullanıcı giriş yapmayı denediğinde sistem otomatik olarak yeni bir geçici şifre üretir ve kullanıcıya e-posta gönderir.
:::

---

## Davet Akışı

Platforma yeni kullanıcı eklemek için şu adımlar izlenir:

1. **İnsanlar** sayfasında ilgili insan personelin kaydını açın. E-posta alanının dolu olduğundan emin olun.
2. Personel satırındaki **zarf ikonuna** tıklayın.
3. Açılan **"Davet Et"** diyalogunda Platform Rolünü seçin.
4. **"Davet Gönder"** butonuna basın.

Arka planda gerçekleşenler:
- `XXXXX-XXXXX` formatında 10 karakterlik geçici şifre üretilir (büyük harf + rakam).
- Şifre `bcrypt` ile hashlenerek veritabanına kaydedilir; `force_change = true` işaretlenir.
- Personelin e-postasına Resend üzerinden davet maili gönderilir; mailde geçici şifre açıkça yer alır.
- Kullanıcı kaydı ve şirket üyeliği oluşturulur.

---

## Şifre Yönetimi

### Kullanıcı Şifre Değiştirme

Giriş yapmış kullanıcılar **Profil** sayfasındaki **"Şifre Değiştir"** sekmesinden şifrelerini güncelleyebilir.

- Mevcut şifre sorulmaz (oturum açık olduğundan kimlik doğrulanmıştır).
- Yeni şifre iki kez girilir ve kaydedilir.

### Admin Şifre Sıfırlama

Kullanıcı şifresini unuttuysa self-servis sıfırlama seçeneği yoktur. Yönetici şu adımları izler:

1. İnsanlar sayfasında ilgili personelin satırına gidin.
2. **Şifre Sıfırla** butonuna tıklayın.
3. Sistem yeni bir 30 dakikalık geçici şifre üretir ve kullanıcıya e-posta gönderir.
4. Kullanıcı bir sonraki girişte `/set-password` sayfasına yönlendirilir.

---

## Rol Hiyerarşisi

Platform beş rol seviyesi içerir. Her rol, üstündeki rollerin tüm yetkilerini kapsar.

| Rol | Türkçe Adı | Açıklama |
|---|---|---|
| `founder` | Kurucu | Tam erişim — tüm sayfalar, ayarlar, kullanıcı yönetimi |
| `executive` | Yönetici | Ayarlar dahil tam erişim; aynı seviyede yeni kullanıcı ekleyemez |
| `dept_head` | Bölüm Yöneticisi | Yapı, Bölümler, İnsanlar, Ajanlar, Org Haritası, İşler, Delegasyon |
| `agent_owner` | Ajan Sorumlusu | Ajanlar, İşler, Delegasyon |
| `user` | Kullanıcı | Yalnızca İşler ve Delegasyon |

---

## Navigasyon Görünürlüğü

Sol kenar çubuğundaki menü öğeleri kullanıcı rolüne göre filtrelenir:

| Menü Öğesi | Minimum Rol |
|---|---|
| Yapı (`/`) | `dept_head` |
| Departmanlar (`/departments`) | `dept_head` |
| İnsanlar (`/personnel`) | `dept_head` |
| Organizasyon (`/org-chart`) | `dept_head` |
| Ajanlar (`/agents`) | `agent_owner` |
| Değişiklik Talepleri (`/change-requests`) | `dept_head` |
| Otonom Akışlar (`/flows`) | `agent_owner` |
| Görev Talepleri / Gelen Kutusu (`/inbox`) | `user` (tüm roller) |
| İşler (`/chat`) | `user` (tüm roller) |
| Delegasyon (`/a2a`) | `user` (tüm roller) |
| Ayarlar (`/settings`) | `executive` |

:::info
`user` rolündeki bir çalışan platforma giriş yaptığında yalnızca **Gelen Kutusu**, **İşler** ve **Delegasyon** sayfalarını görür.
:::

---

## Profil Sayfası

Her kullanıcı sağ üst köşedeki avatar menüsünden **Profil** sayfasına erişebilir. Profil sayfasında:

- **Ad ve E-posta:** `authStore`'dan alınan gerçek kullanıcı bilgileri
- **Şirket Üyelikleri:** Kullanıcının dahil olduğu şirketlerin listesi ve her şirketteki rolü (renkli rozet)
- **Şifre Değiştir sekmesi:** Mevcut şifre sorulmadan yeni şifre belirleme

---

## Backend API Referansı

| Endpoint | Yöntem | Açıklama | Yetki |
|---|---|---|---|
| `/auth/token` | POST | Giriş — `email` + `password` döner `access_token` | Herkese açık |
| `/auth/me` | GET | Oturum açmış kullanıcı bilgisi + şirket üyelikleri | Bearer token |
| `/auth/invite` | POST | Yeni kullanıcı oluştur + davet e-postası gönder | `manager+` |
| `/auth/change-password` | POST | Şifre güncelle | Bearer token |
| `/auth/reset/{user_id}` | POST | Admin şifre sıfırlama | `manager+` |
| `/personnel/{id}/invite` | POST | Personel kaydından doğrudan davet | `manager+` |

### Token Kullanımı

Başarılı giriş sonrası dönen `access_token` tüm yetkili endpoint çağrılarında HTTP header olarak gönderilir:

```
Authorization: Bearer <access_token>
```

Token, `JWT_SECRET` ortam değişkeniyle imzalanır. Süre dolunca yeniden giriş gerekir.

---

## Telegram Bildirim Altyapısı

Davet ve şifre sıfırlama bildirimleri **Telegram Bot API** üzerinden iletilir. E-posta altyapısı gerektirmez; anlık teslimat ve çift yönlü iletişim sağlar.

Gönderilen bildirim türleri:
- **Davet bildirimi:** Yeni kullanıcının geçici şifresi admin chat'e iletilir
- **Şifre yenileme:** Süresi dolan geçici şifre yenilendiğinde bildirim gönderilir
- **Admin sıfırlama:** Yönetici şifre sıfırladığında yeni geçici şifre bildirilir

Yapılandırma: **Ayarlar → Entegrasyonlar → Telegram Bildirimleri** bölümünden BotFather token'ı ve admin chat ID girilir.

Telegram yapılandırılmamışsa geçici şifreler API yanıtında ve arayüzde gösterilir.

Kurulum detayları için → [Kurulum — Telegram Bot Kurulumu](../getting-started/installation.md#telegram-bot-kurulumu)
