---
sidebar_position: 8
---

# Sosyal Medya Ajan Skill'leri

Platform, ajanlara Instagram ve WhatsApp yetenekleri eklemek için iki yerleşik (builtin) skill sunar:

- `instagram_post` — Instagram Business hesabına fotoğraf + caption yayınlama
- `whatsapp_send` — WhatsApp Business Cloud API üzerinden metin mesajı gönderme

---

## Ön Koşullar

### Instagram

- Bir **Instagram Business** veya **Creator** hesabı
- Hesabın bağlı olduğu bir **Facebook Sayfası**
- Meta App'e eklenen izinler: `instagram_basic`, `instagram_content_publish`
- [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/) üzerinden alınan **Page Access Token** (süresiz için uzun ömürlü token)
- Hesabın **IG Business User ID**'si

### WhatsApp

- **WhatsApp Business** hesabı (Meta Business Suite üzerinden)
- Meta App'e eklenen izin: `whatsapp_business_messaging`
- **Phone Number ID** (Meta Business Dashboard → WhatsApp → Getting Started)
- **System User Access Token** (Business Settings → System Users)

> **Not:** WhatsApp Status (Durum/Hikâye) resmi Cloud API'de desteklenmez. Bu skill belirtilen numaraya metin mesajı gönderir.

---

## Yapılandırma

1. **Ayarlar → Sosyal Medya** sekmesine gidin.
2. Instagram bölümüne **IG Business User ID** ve **Access Token** girin.
3. WhatsApp bölümüne **Phone Number ID**, **Access Token** ve isteğe bağlı **Varsayılan Alıcı** (E.164 format, örn. `+905551234567`) girin.
4. **Kaydet**'e tıklayın. Kimlik bilgileri AES-256 ile şifreli saklanır.

---

## Ajana Skill Ekleme

1. **Personel** listesinden ajana tıklayın.
2. **Ajan Yapılandırması** bölümüne gidin.
3. **Skill Ekle** → **Skill türü: builtin** seçin.

| Skill Adı | Tip | Açıklama |
|---|---|---|
| `instagram_post` | builtin | Fotoğraf + caption ile Instagram gönderisi |
| `whatsapp_send` | builtin | WhatsApp mesajı gönderimi |

### instagram_post parametreleri

| Parametre | Zorunlu | Açıklama |
|---|---|---|
| `image_url` | ✅ | Halka açık bir görsel URL'si (HTTPS) |
| `caption` | ✅ | Post açıklaması (hashtag dahil) |

### whatsapp_send parametreleri

| Parametre | Zorunlu | Açıklama |
|---|---|---|
| `message` | ✅ | Gönderilecek metin |
| `to` | ❌ | Alıcı numarası (E.164). Boşsa varsayılan alıcı kullanılır |

---

## Örnek Kullanım

Ajanla sohbet sırasında:

```
Sen: Bugünkü kampanyamız için bir Instagram gönderisi paylaş:
     Görsel: https://cdn.example.com/promo.jpg
     Caption: Yeni sezon koleksiyonumuz çıktı! 🚀 #fabrika #yazilim

Ajan: [instagram_post çağrısı] → ✅ Instagram'a yayınlandı — medya ID: 17900000000000000
```

```
Sen: +905551234567 numarasına proje güncellemesini yaz: "Sprint 4 tamamlandı, test ortamı hazır."

Ajan: [whatsapp_send çağrısı] → ✅ WhatsApp mesajı gönderildi → +905551234567
```

---

## API Endpoint'leri

| Endpoint | Açıklama |
|---|---|
| `GET /social-media/config` | Mevcut yapılandırmayı döner |
| `PUT /social-media/config` | Yapılandırmayı kaydeder/günceller |
| `DELETE /social-media/config` | Tüm kimlik bilgilerini siler |
| `POST /social-media/instagram/post` | Doğrudan Instagram gönderisi oluşturur |
| `POST /social-media/whatsapp/send` | Doğrudan WhatsApp mesajı gönderir |
