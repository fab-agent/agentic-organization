---
sidebar_position: 5
---

# Yetenekler ve Politikalar

## Yetenekler (skill)

Yetenek, ajanın kullanabildiği bir araçtır. **Yapı → Yetenekler** sayfası şirket geneli bir **kütüphanedir**: bir yetenek bir kez tanımlanır, istenen ajanlara atanır.

Her yeteneğin adı, slug'ı, kısa açıklaması, **türü**, Markdown **içeriği** (ajana nasıl ve ne zaman kullanacağını anlatan talimat), türe özgü ayarı ve aktif/pasif durumu vardır.

### Yetenek türleri

| Tür | Ne yapar | Ayar |
|---|---|---|
| **Dahili** (`builtin`) | Platformun hazır araçları | Aşağıdaki liste |
| **MCP** | Bir MCP sunucusunun aracını çağırır (HTTP üzerinden JSON-RPC; sunucu `…/call` adresini sunmalı) | Sunucu adresi; kimlik doğrulama: yok, API anahtarı veya Bearer token |
| **HTTP API** | Bir REST webhook veya API'yi çağırır (`POST` varsayılan, `GET` seçilebilir) | Adres, yöntem, sabit başlıklar |
| **Fonksiyon** | Özel Python kodu; `run(args: dict) -> str` imzası gerekir. Kısıtlı bir ortamda (az sayıda yerleşik fonksiyon) ve **5 saniye** zaman aşımıyla çalışır | Kod |
| **Veritabanı** | Bağlı bir veritabanında SQL sorgusu çalıştırır | Bağlantı ve şema ([Ayarlar → Veritabanları](/guide/settings#veritabanları)) |

Teknik şemalar için: [Yetenek Türleri](/technical/skill-types).

### Dahili araçlar

| Araç | İşlevi |
|---|---|
| Web arama (`web_search`) | DuckDuckGo ile internet araması |
| Grafik üretimi (`text_to_chart`) | JSON/CSV verisinden grafik. **Şu an yer tutucu:** araç çağrılır ama gerçek bir grafik üretmez |
| Günlük yaz (`journal_write`) | Oturum günlüğüne Markdown girişi ekler |
| Ajan delegasyonu (`delegate_to_agent`) | Görevi başka bir ajana devreder → [Delegasyon](/guide/delegation) |
| Instagram gönderi (`instagram_post`) | Instagram Business hesabında paylaşım → [Ayarlar → Sosyal medya](/guide/settings#entegrasyonlar) |
| WhatsApp mesaj (`whatsapp_send`) | WhatsApp Business API ile mesaj |

### Ajana atama

Ajan oluştururken/düzenlerken **Yetenekler** bölümünden kütüphaneden seçilir veya o ajana özel bir araç eklenir. Yetenek düzenlemeleri **onay sürecine** gider (bölüm yöneticisi + yönetici); onaylanana kadar eski hâli geçerlidir. → [Değişiklik Talepleri](/guide/change-requests)

## Politikalar

Politika, ajanların uyacağı yazılı bir kuraldır; **Markdown belgesi** olarak yazılır. Üç kapsamı vardır:

| Kapsam | Kime uygulanır |
|---|---|
| **Şirket** | Şirketteki tüm ajanlar |
| **Departman** | O departmandaki ajanlar (departmana bağlanınca otomatik) |
| **Ajan** | Yalnızca o ajan (ajana özel ek politika) |

**Yapı → Politikalar** sayfasından oluşturulur, düzenlenir, aktif/pasif yapılır. Düzenlemeler yetenekler gibi onaya gider.

### Politika ajanı nasıl etkiler?

- Ajanın talimatına, uyması gereken politikaların **adları** eklenir.
- Politika metninde `policy`, `yaml` veya `json` olarak işaretlenmiş bir kod bloğu varsa, **politika motoru** bunu çalıştırılabilir kural olarak okur ve ajanın araç çağrılarını `izin ver / sor / reddet` olarak değerlendirir. Motor varsayılan olarak **deneme kipinde** (`dry_run`: karar kaydedilir ama engellenmez) çalışır. Kipi (`off`, `dry_run`, `enforce`) şu an yalnızca API ile değiştirilebilir: `PUT /policies/config`. Ayrıntı: [Politika Motoru](/workstation/policy-engine).

Yani düz yazı bir politika, ajanı yönlendiren bir rehberdir; **kesin zorlama** için kural bloğu yazmanız ve motoru `enforce` kipine almanız gerekir (arayüzde bu ayar henüz yok).
