---
id: github-integration
title: GitHub Entegrasyonu
sidebar_label: GitHub Entegrasyonu
---

# GitHub Entegrasyonu

fab.engineering, her şirket için bir GitHub organizasyonu bağlanmasına izin verir. Bağlantı kurulduktan sonra, onaylanan değişiklik talepleri otomatik olarak bu repoya commit edilir.

---

## Genel Bakış

| Özellik | Açıklama |
|---|---|
| Kimlik doğrulama | Personal Access Token (PAT) |
| Kapsam | Şirket başına tek bir GitHub org |
| Tetikleyici | Admin onaylı Değişiklik Talebi |
| Commit kaydı | SHA ve URL, talep kaydında saklanır |

---

## Kurulum

**Ayarlar** (`/settings`) sayfasında **Git Entegrasyonu** sekmesine geçin.

### 1. GitHub PAT Oluşturun

GitHub hesabınızda **Settings → Developer settings → Personal access tokens → Tokens (classic)** yolunu izleyin:

- **repo** izni (private repolar için) veya **public_repo** izni (yalnızca public repolar için)
- İsteğe bağlı: belirli bir süre sınırı belirleyin

:::caution
Token ile giriş bilgileri repo içeriğine tam erişim sağlar. Token'ı yalnızca fab.engineering entegrasyonu için kullanın ve başkasıyla paylaşmayın.
:::

### 2. Bağlantı Bilgilerini Girin

Ayarlar — Git Entegrasyonu formunda şu alanları doldurun:

| Alan | Açıklama | Örnek |
|---|---|---|
| **GitHub Org / Kullanıcı** | GitHub organizasyon veya kullanıcı adı | `my-company` |
| **Repo Adı** | Hedef repo adı | `agent-configs` |
| **Branch** | Commit'lerin atılacağı dal | `main` |
| **GitHub PAT** | Personal Access Token | `ghp_...` |

**Bağla** butonuna basın. Sistem test commit'i yapmadan token geçerliliğini doğrular.

### 3. Bağlantıyı Test Edin

Bağlantı kurulduktan sonra **Test Et** butonu görünür. Bu buton:
- Verilen token ile repoya erişim sağlanabildiğini doğrular.
- Sonucu anlık olarak ekranda gösterir (`Bağlı` / `Hata`).

---

## Sync Log

Ayarlar — Git Entegrasyonu sayfası, son commit işlemlerini listeleyen bir **Sync Log** tablosu içerir. Her satırda:

- Commit tarih/saati
- Commit SHA (GitHub'a tıklanabilir bağlantı)
- İşlem sonucu (`success` / `error`)
- Hata varsa kısa hata mesajı

---

## Commit Akışı

Bir Değişiklik Talebi admin tarafından onaylandığında:

```
Admin "Onayla & Commit Et" → backend commit akışı
    ↓
GitHub API ile repo içeriği çekilir
    ↓
Ajan yapılandırma dosyası güncellenir
    ↓
Güncellenmiş dosya GitHub'a push edilir
    ↓
SHA ve commit URL, ChangeRequest kaydına yazılır
    ↓
Gelen Kutusu'na "commit başarılı" bildirimi düşer
```

---

## Bağlantı Kesme

Ayarlar — Git Entegrasyonu sayfasındaki **Bağlantıyı Kes** butonu:
- GitHub yapılandırmasını siler (PAT dahil).
- Mevcut Değişiklik Taleplerindeki SHA kayıtlarına dokunmaz.
- Bundan sonraki admin onayları commit adımı olmadan tamamlanır.

---

## Sık Karşılaşılan Sorunlar

| Sorun | Olası Neden | Çözüm |
|---|---|---|
| `401 Unauthorized` | PAT süresi dolmuş | Yeni token oluşturup tekrar bağlayın |
| `404 Not Found` | Repo adı veya org adı yanlış | Ayarları kontrol edin |
| `403 Forbidden` | Token'ın repo izni eksik | PAT oluştururken `repo` iznini seçin |
| Commit başarısız, log görünmüyor | Branch korumalı (protected) | Branch koruma kuralını devre dışı bırakın veya bot kullanıcısına izin verin |

---

## API Endpoint'leri

| Endpoint | Yöntem | Açıklama | İzin |
|---|---|---|---|
| `/git/config?company_id=` | GET | Mevcut Git yapılandırması | `executive+` |
| `/git/config` | POST | Yapılandırma kaydet / güncelle | `executive+` |
| `/git/config?company_id=` | DELETE | Yapılandırmayı sil | `executive+` |
| `/git/test?company_id=` | POST | Bağlantı testi | `executive+` |
| `/git/logs?company_id=` | GET | Sync log listesi | `executive+` |
