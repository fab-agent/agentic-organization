# Provider Key Management (F2)

Bu sayfa, 3rdParty Agent Organization platformunda **provider API anahtarlarının** güvenli yönetimi ile ilgili sistemi açıklamaktadır.

## Desteklenen Sağlayıcılar

| Sağlayıcı | Kimlik | Modeller |
|---|---|---|
| Anthropic | `anthropic` | Claude Opus 4.7, Sonnet 4.6, Haiku 4.5 |
| OpenAI | `openai` | GPT-4o, GPT-4o Mini, o1 Mini |
| Google | `google` | Gemini 2.5 Pro, Gemini 2.0 Flash |
| Mistral AI | `mistral` | Mistral Large, Mistral Small |
| Alibaba Qwen | `qwen` | Qwen Max, Qwen Plus, Qwen Turbo, Qwen Long |

Qwen, DashScope'un OpenAI uyumlu API'sini (`dashscope.aliyuncs.com/compatible-mode/v1`) kullanır. Key [DashScope Console](https://dashscope.console.aliyun.com/) üzerinden alınır.

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