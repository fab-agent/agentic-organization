# Provider Key Management (F2)

Bu sayfa, 3rdParty Agent Organization platformunda **provider API anahtarlarının** güvenli yönetimi ile ilgili sistemi açıklamaktadır.

## Genel Bakış

Platform, birden fazla AI sağlayıcısı (Anthropic, OpenAI, Google, Mistral vb.) ile çalışabildiği için, bu sağlayıcılara ait API anahtarlarının güvenli bir şekilde saklanması ve yönetilmesi kritik öneme sahiptir.

## Mimari

### Bileşenler

- **core/security.py**: Fernet (AES) tabanlı şifreleme ve şifre çözme işlemleri.
- **services/provider_service.py**: Provider API anahtarlarının test edilmesi (httpx ile canlı çağrı).
- **api/providers.py**: Provider key CRUD ve test endpoint'leri.

### Veri Modeli

- `ProviderKey` tablosu:
  - `provider` (string, unique)
  - `encrypted_key` (string)
  - `is_active` (boolean)
  - `last_tested` (datetime)
  - `status` (active / invalid)

## Endpoint'ler

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| POST | `/providers/{provider}/key` | Şifreli key kaydeder ve test eder |
| GET | `/providers/status` | Tüm provider'ların anlık durumu |
| GET | `/providers/models` | Sadece aktif provider'ların modelleri |
| DELETE | `/providers/{provider}/key` | Key silme |

## Güvenlik

- Tüm API anahtarları **Fernet (AES-128)** ile şifrelenerek saklanır.
- Şifreleme anahtarı `.secret` dosyasında tutulur (`.env` veya environment variable ile de yönetilebilir).
- Key'ler hiçbir zaman plaintext olarak döndürülmez.

## Kullanım Akışı

1. Kullanıcı (admin) provider key'ini ekler.
2. Sistem key'i şifreler ve kaydeder.
3. Key test edilir (gerçek API çağrısı ile).
4. Sonuç `active` veya `invalid` olarak işaretlenir.

## İlgili Sprint

- **Sprint 2** kapsamında F2 (Provider Key Management) tamamlanmıştır.

---
*Son güncelleme: 1 Haziran 2026*