---
sidebar_position: 2
---

# Merkezî LLM Gateway

> ADR-0004 · `backend/api/gateway.py`, `backend/services/gateway_auth.py`,
> `backend/services/gateway_limits.py`

İş istasyonundaki ajanlar model sağlayıcısına **doğrudan** bağlanmaz. Bunun
yerine platformun sunduğu OpenAI uyumlu proxy'ye bağlanırlar. Böylece tek bir
noktadan: kimlik doğrulama, kota, model kısıtı, kullanım ölçümü ve denetim
kaydı geçer.

---

## Endpoint'ler

| Method | Yol | Açıklama |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI uyumlu sohbet tamamlama (streaming dahil) |
| `GET`  | `/v1/models` | Persona'nın erişebildiği modeller |
| `POST` | `/policy/decide` | Bir araç çağrısı için politika kararı (plugin kullanır) |
| `GET`  | `/gateway/usage` | Persona'nın güncel kullanım/kota durumu |
| `POST` | `/gateway/persona-token` | Kısa ömürlü persona token'ı üret (sahip kapsamlı) |

İstek `Authorization: Bearer <persona-token>` başlığı ile gelir. Token
doğrulaması `services/gateway_auth.py` içindedir (jose, HS256).

---

## BYO upstream

Gateway'in kendi model anahtarı yoktur. Her istekte upstream, şirketin
`ProviderKey` kaydından çözülür:

```
persona → company → ProviderKey(active)
                       ├── base_url   (ör. https://api.anthropic.com/v1)
                       └── api_key    (Fernet ile şifreli, çözülüp iletilir)
```

Model önekine göre doğru `ProviderKey` seçilir. OpenAI uyumlu her endpoint
(Anthropic, OpenAI, Google, Mistral, Qwen, Ollama, LM Studio, self-hosted vLLM …)
desteklenir.

---

## Streaming ve kullanım ölçümü

SSE yanıtı upstream'den birebir geçirilir (`_proxy_stream`). Akışlı çağrıların
token tüketimini yakalayabilmek için istek gövdesine
`stream_options.include_usage = true` enjekte edilir; gelen son `usage` olayı
(`_sse_usage`) ayrıştırılıp `GatewayUsage` sayaçlarına işlenir.

Akışsız çağrılarda `usage` alanı doğrudan yanıttan okunur.

---

## Guardrail'lar

`services/gateway_limits.py` — tamamı varsayılan olarak **serbest**, açıkça
yapılandırılınca devreye girer:

| Kısıt | Nasıl |
|---|---|
| Model allow-list | Persona/şirket için izinli model listesi; liste boşsa hepsi serbest |
| Hız sınırı | Persona başına istek/dakika |
| Token kotası | Günlük ve aylık token tavanı (`GatewayUsage` tablosundan) |

Kota aşıldığında istek `429` ile reddedilir. `GET /gateway/usage` mevcut
tüketimi ve kalan bütçeyi döner.

---

## Denetim

Her gateway çağrısı `services/audit_chain.py` `record()` üzerinden
`gateway_call` olayı olarak denetim zincirine yazılır (model, token sayıları,
persona, sonuç). Bkz. [Denetim Zinciri](./audit-chain.md).

---

## Açık konular

- Çok worker'lı dağıtımda hız sınırı / kota için Redis destekli sayaç
  (Postgres advisory lock hâlihazırda PG'yi kapsıyor).
- Upstream 200 dışı bir stream status döndürdüğünde davranış.
