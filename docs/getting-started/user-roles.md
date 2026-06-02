---
id: user-roles
title: Kullanıcı Rolleri
sidebar_label: Kullanıcı Rolleri
---

# Kullanıcı Rolleri

fab.engineering, beş farklı platform rolü tanımlar. Hangi sayfaların göründüğü ve hangi işlemlerin yapılabildiği bu role göre belirlenir.

---

## Rolüme Göre Ne Görebilirim?

### Kurucu (`founder`)

Platformun tam yetkili sahibi. Tüm sayfalara ve işlemlere erişebilir.

**Erişilen sayfalar:** Yapı · Departmanlar · İnsanlar · Organizasyon · Ajanlar · Değişiklik Talepleri · Otonom Akışlar · Gelen Kutusu · İşler · Delegasyon · Ayarlar

**Yapabilecekler:**
- Tüm şirket, departman, personel ve ajan yönetimi
- Kullanıcıları platforma davet etme ve rol atama
- Diğer kullanıcıların şifrelerini sıfırlama
- Ayarlar sayfasında AI sağlayıcı anahtarları ve Git entegrasyonu yönetimi

---

### Yönetici (`executive`)

Kurucu ile neredeyse aynı yetkiye sahip. Kendi düzeyindeki veya üstündeki kullanıcı ekleyemez.

**Erişilen sayfalar:** Yapı · Departmanlar · İnsanlar · Organizasyon · Ajanlar · Değişiklik Talepleri · Otonom Akışlar · Gelen Kutusu · İşler · Delegasyon · Ayarlar

**Yapabilecekler:**
- Tüm organizasyon ve personel yönetimi
- `dept_head`, `agent_owner` ve `user` rolünde kullanıcı davet etme
- Şifre sıfırlama
- Ayarlar sayfasına tam erişim

---

### Bölüm Yöneticisi (`dept_head`)

Operasyonel yönetim rolü. Organizasyon yapısını ve personeli görebilir; Ayarlar sayfasına erişemez.

**Erişilen sayfalar:** Yapı · Departmanlar · İnsanlar · Organizasyon · Ajanlar · Değişiklik Talepleri · Gelen Kutusu · İşler · Delegasyon

**Yapabilecekler:**
- Departman oluşturma, düzenleme ve hiyerarşi kurma
- Personel ekleme ve e-posta ile platform daveti gönderme
- Ajan yapılandırma ve durum yönetimi
- Değişiklik taleplerini bölüm adına onaylama veya reddetme
- Org haritasını görüntüleme (personel ve departman görünümleri)
- Ajanlarla sohbet etme (İşler)
- Gelen Kutusu mesajlarını okuma ve görev talepleri yönetme
- Delegasyon işlemleri

---

### Ajan Sorumlusu (`agent_owner`)

Ajan odaklı operasyonel rol. Organizasyon yapısını göremez.

**Erişilen sayfalar:** Ajanlar · Otonom Akışlar · Gelen Kutusu · İşler · Delegasyon

**Yapabilecekler:**
- Sorumlu olduğu ajanları görüntüleme ve yapılandırma
- Otonom akış oluşturma ve yönetme
- Gelen Kutusu mesajlarını okuma ve bekleyen görev taleplerini işleme
- Ajanlarla sohbet etme
- Delegasyon işlemleri

---

### Kullanıcı (`user`)

En dar kapsamlı rol. Yalnızca günlük çalışma alanına erişebilir.

**Erişilen sayfalar:** Gelen Kutusu · İşler · Delegasyon

**Yapabilecekler:**
- Görev talebi oluşturma (departman/skill filtreyle ajan talep etme)
- Gelen Kutusu mesajlarını okuma ve bekleyen görev taleplerini işleme
- Ajanlarla sohbet etme (İşler sayfası)
- Delegasyon işlemleri

---

## Karşılaştırma Tablosu

| Sayfa / İşlem | Kullanıcı | Ajan Sorumlusu | Bölüm Yöneticisi | Yönetici | Kurucu |
|---|:---:|:---:|:---:|:---:|:---:|
| Gelen Kutusu | Evet | Evet | Evet | Evet | Evet |
| İşler (Sohbet) | Evet | Evet | Evet | Evet | Evet |
| Delegasyon | Evet | Evet | Evet | Evet | Evet |
| Görev Talebi Oluşturma | Evet | Evet | Evet | Evet | Evet |
| Ajanlar | — | Evet | Evet | Evet | Evet |
| Otonom Akışlar | — | Evet | Evet | Evet | Evet |
| Yapı (Dashboard) | — | — | Evet | Evet | Evet |
| Departmanlar | — | — | Evet | Evet | Evet |
| İnsanlar | — | — | Evet | Evet | Evet |
| Organizasyon (Org Haritası) | — | — | Evet | Evet | Evet |
| Değişiklik Talepleri | — | — | Evet | Evet | Evet |
| Bölüm Onayı (Değişiklik) | — | — | Evet | Evet | Evet |
| Admin Onayı + Git Commit | — | — | — | Evet | Evet |
| Ayarlar (AI + Git) | — | — | — | Evet | Evet |
| Kullanıcı Davet Etme | — | — | Evet | Evet | Evet |
| Şifre Sıfırlama | — | — | Evet | Evet | Evet |

---

## Rolünüzü Nasıl Öğrenirsiniz?

Sağ üst köşedeki avatar menüsüne tıklayın → **Profil** sayfasını açın.

Profil sayfasında **Şirket Üyelikleri** bölümü, dahil olduğunuz her şirketi ve o şirketteki rolünüzü renkli rozet şeklinde gösterir.

---

## Rol Değişikliği

Rol değişikliği self-servis yapılamaz. `dept_head` veya üzeri yetkideki bir yöneticinin sizi yeniden davet etmesi ya da mevcut üyeliğinizi düzenlemesi gerekir. Rol değişikliği talebi için şirket yöneticinize başvurun.

---

## Teknik Detaylar

Kimlik doğrulama akışı, token yapısı ve backend API'si için → [Kimlik Doğrulama ve Roller](../platform/auth-and-roles.md)
