---
id: personnel-portal
title: İnsanlar Sayfası
sidebar_label: İnsanlar
---

# İnsanlar Sayfası

İnsanlar sayfası, şirkete ait tüm insan personelin listelendiği ve platform erişiminin yönetildiği merkezdir.

## Genel Bakış

İnsanlar sayfası üzerinden şu işlemler gerçekleştirilir:

- Şirkete ait insan personeli listeleme, ekleme, düzenleme
- Personele e-posta adresi tanımlama
- Platform daveti gönderme ve erişim durumunu takip etme
- Admin şifre sıfırlama

---

## Personel Tablosu

Tabloda her insan personel için şu sütunlar görünür:

| Sütun | Açıklama |
|---|---|
| **Ad Soyad** | Personelin adı ve unvanı |
| **Departman** | Bağlı olduğu departman |
| **E-posta** | Platform daveti için kullanılan e-posta adresi |
| **Platform** | Kullanıcı hesabının durumu |

**Platform sütunu iki durumu gösterir:**

- **Aktif** (yeşil, kullanıcı ikonu ile): Personelin aktif bir platform hesabı var.
- **Davet edilmedi** (zarf ikonu ile): Personelin e-postası var ama henüz davet gönderilmemiş.

E-postası olmayan personeller için Platform sütununda hiçbir şey gösterilmez.

---

## Platform Daveti Gönderme

Bir personeli platforma davet etmek için:

1. **İnsanlar** sayfasına gidin ve ilgili personelin kaydını açın (veya yeni kayıt eklerken e-posta girin).
2. **E-posta** alanının dolu olduğundan emin olun.
3. Tablodaki zarf (mail) ikonuna tıklayın.
4. **"Davet Et"** diyalogu açılır. Açılan listeden kullanıcıya uygun **Platform Rolünü** seçin:
   - `Kurucu (founder)`
   - `Yönetici (executive)`
   - `Bölüm Yöneticisi (dept_head)`
   - `Ajan Sorumlusu (agent_owner)`
   - `Kullanıcı (user)`
5. **"Davet Gönder"** butonuna basın.

Sistem şunları otomatik olarak yapar:
- `XXXXX-XXXXX` formatında (büyük harf + rakam) **30 dakika geçerli** geçici şifre üretir.
- Personelin e-postasına Resend üzerinden davet maili gönderir. Mailde geçici şifre açıkça yer alır.
- Veritabanında kullanıcı hesabı ve şirket üyeliği kaydı oluşturur.
- Tablodaki satır **"Aktif"** olarak güncellenir.

:::info
Davet butonu yalnızca şu koşulların hepsini sağlayan personeller için görünür: Tür = İnsan, E-posta dolu ve henüz platform hesabı yok.
:::

---

## Geçici Şifre Süre Dolumu

Davet gönderildikten sonra kullanıcı 30 dakika içinde giriş yapmazsa geçici şifre geçersiz hale gelir. Kullanıcı giriş yapmayı denediğinde:

1. Sistem otomatik olarak yeni bir geçici şifre üretir.
2. Kullanıcıya anında yeni şifre içeren e-posta gönderilir.
3. Kullanıcı yeni şifreyle giriş yapabilir.

Yönetici el ile de **Şifre Sıfırla** butonuna basarak yeni geçici şifre gönderebilir.

---

## İlk Giriş Akışı (Kullanıcı Tarafı)

1. Kullanıcı e-postasındaki geçici şifreyi alır.
2. `/login` sayfasına gider, e-posta ve geçici şifreyi girer.
3. Sistem `/set-password` sayfasına yönlendirir.
4. Kullanıcı yeni kalıcı şifresini iki kez girer ve kaydeder.
5. Ana sayfaya yönlendirilir; artık kendi rolüne göre platformu kullanabilir.

---

## Personel Ekleme

**"Yeni Personel"** butonuna basıldığında açılan formda zorunlu ve opsiyonel alanlar:

| Alan | Zorunlu | Açıklama |
|---|---|---|
| Ad Soyad | Evet | |
| Slug | Evet | Otomatik oluşturulur, düzenlenebilir |
| Ünvan | — | Görüntülenen pozisyon |
| Tür | Evet | **İnsan** veya **Ajan** |
| Departman | — | Bağlanacak departman |
| Yönetici | — | Raporlama hiyerarşisi |
| **E-posta** | — | Platform daveti için; insan türündeki personelde önerilir |

---

## Rol Detayları

Her rolün erişebildiği sayfalar ve yapabilecekleri için → [Kullanıcı Rolleri](../getting-started/user-roles.md)  
Teknik kimlik doğrulama dokümantasyonu için → [Kimlik Doğrulama ve Roller](../platform/auth-and-roles.md)