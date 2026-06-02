---
id: admin-panel
title: Kullanıcı ve Erişim Yönetimi
sidebar_label: Kullanıcı Yönetimi
---

# Kullanıcı ve Erişim Yönetimi

fab.engineering, davet tabanlı bir kullanıcı sistemi kullanır. Kimse sisteme kendi kendine kayıt olamaz; tüm kullanıcılar yöneticiler tarafından İnsanlar sayfasındaki personel kayıtları üzerinden platforma davet edilir.

---

## Kullanıcı Oluşturma Akışı

### 1. Personel Kaydına E-posta Ekle

**İnsanlar** sayfasına gidin. İlgili insan personelin kaydını açın veya yeni kayıt oluştururken **E-posta** alanını doldurun.

- Personelin türü **İnsan** olmalıdır (Ajan türündeki kayıtlara davet gönderilmez).
- E-posta alanı doldurulmuş ama henüz davet edilmemiş personeller tabloda **"Davet edilmedi"** etiketi ile görünür.

### 2. Davet Gönder

Personel satırındaki zarf (mail) ikonuna tıklayın. **"Davet Et"** başlıklı bir diyalog açılır.

Diyalogda:
1. **Platform Rolü** seçin: `founder`, `executive`, `dept_head`, `agent_owner` veya `user`.
2. **"Davet Gönder"** butonuna basın.

Sistem arka planda şunları yapar:
- `XXXXX-XXXXX` formatında 10 karakterlik geçici şifre üretir (büyük harf + rakam, 30 dakika geçerli).
- Seçilen e-posta adresine Resend üzerinden davet e-postası gönderir. E-postada geçici şifre açıkça görünür.
- Veritabanında kullanıcı hesabı ve şirket üyeliği oluşturulur.
- İnsanlar tablosundaki satır **"Aktif"** (yeşil, kullanıcı ikonu) olarak güncellenir.

### 3. Kullanıcı İlk Girişi Yapar

Kullanıcı `/login` sayfasına gider, e-posta ve geçici şifresini girer. Sistem şifreyi `force_change` olarak işaretlediğinden otomatik olarak `/set-password` sayfasına yönlendirir. Kullanıcı yeni kalıcı şifresini belirler ve platforma giriş yapar.

---

## Şifre Sıfırlama (Admin)

Kullanıcı şifresini unuttuysa self-servis sıfırlama yoktur. Yönetici şu adımları izler:

1. İnsanlar sayfasında ilgili personelin satırına gidin.
2. Şifre sıfırlama butonuna tıklayın.
3. Sistem yeni bir 30 dakikalık geçici şifre üretir ve kullanıcıya e-posta ile gönderir.
4. Kullanıcı bir sonraki girişte `/set-password` sayfasına yönlendirilir.

:::info
Geçici şifre süresi dolmuşsa kullanıcı giriş yapmayı denediğinde sistem otomatik olarak yeni bir geçici şifre oluşturur ve kullanıcıya anında e-posta gönderir.
:::

---

## Rol Yönetimi

Kullanıcıların platform rolü, davet sırasında belirlenir. Rol değişikliği için İnsanlar sayfasındaki kullanıcı üyeliği düzenleme arayüzü kullanılır.

Rol hiyerarşisi ve her rolün erişim kapsamı için → [Kimlik Doğrulama ve Roller](../platform/auth-and-roles.md)

---

## API Endpoint'leri

Kullanıcı yönetimiyle ilgili backend endpoint'leri:

| Endpoint | Yöntem | Açıklama | İzin |
|---|---|---|---|
| `/auth/token` | POST | Giriş (e-posta + şifre) | Herkese açık |
| `/auth/me` | GET | Oturum açmış kullanıcı + üyelikler | Giriş gerekli |
| `/auth/invite` | POST | Kullanıcı oluştur + davet e-postası gönder | `manager+` |
| `/auth/change-password` | POST | Şifre değiştir (mevcut şifre gerekmez) | Giriş gerekli |
| `/auth/reset/{user_id}` | POST | Admin şifre sıfırlama | `manager+` |
| `/personnel/{id}/invite` | POST | Personel kaydından doğrudan davet | `manager+` |

Detaylı API dokümantasyonu → [API Genel Bakış](../api/overview.md)
