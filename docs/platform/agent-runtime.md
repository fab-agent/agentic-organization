---
sidebar_position: 1
---

# Agent Runtime (F6B)

Bu belge, platform içindeki ajan çalıştırma motorunun işleyişini açıklar: oturum yaşam döngüsü, SSE akışı, çoklu provider desteği ve araç çağrısı döngüsü.

---

## Oturum Yaşam Döngüsü

Her konuşma bir `AgentSession` kaydıyla başlar. Bir oturumda birden fazla mesaj gidip gelebilir; her mesaj agentic döngüyü tetikler.

```
POST /sessions                    → Oturum oluştur
POST /sessions/{id}/messages      → Mesaj gönder (SSE akışı döner)
GET  /sessions/{id}               → Oturum + mesaj geçmişini getir
GET  /sessions                    → Oturum listesi
DELETE /sessions/{id}             → Oturumu kapat
```

Bir oturum oluştururken `personnel_id` (ajan türünde bir personel) zorunludur:

```json
POST /sessions
{ "personnel_id": "uuid", "title": "Opsiyonel başlık" }
```

### Oturum Durumları

| Durum | Anlamı |
|---|---|
| `active` | Mesaj gönderilebilir |
| `closed` | Oturum sonlandırıldı, yalnızca okunabilir |

---

## Mesaj Gönderme ve SSE Akışı

Bir mesaj gönderildiğinde backend SSE (Server-Sent Events) akışıyla yanıt verir. Yanıt HTTP'nin doğal akış mekanizmasını kullanır — WebSocket değil.

```
POST /sessions/{session_id}/messages
Content-Type: application/json

{ "content": "Bugünkü satış rakamlarını göster" }
```

Yanıt: `Content-Type: text/event-stream`

Her olay `data: {json}\n\n` biçiminde iletilir.

### SSE Olay Türleri

| `type` | Açıklama |
|---|---|
| `text` | LLM'den gelen metin parçası |
| `tool_call` | Model bir araç çağırdı |
| `tool_result` | Araç sonucu döndü |
| `done` | Mesaj tamamlandı, `message_id` ile DB'ye kaydedildi |
| `error` | Çalışma zamanı hatası |
| `stream_end` | Akış kapanıyor (hata durumunda bile gönderilir) |

Örnek olay dizisi:

```
data: {"type":"text","content":"Merhaba, rakamları"}
data: {"type":"text","content":" getiriyorum..."}
data: {"type":"tool_call","name":"web_search","args":{"query":"Q2 satış"}}
data: {"type":"tool_result","name":"web_search","result":"Q2 2026: 142K TL"}
data: {"type":"text","content":"Q2 satışları 142K TL olarak gerçekleşti."}
data: {"type":"done","message_id":"abc123"}
data: {"type":"stream_end"}
```

:::tip EventSource yerine fetch + ReadableStream
`EventSource` API'si yalnızca GET isteklerini destekler. Mesaj içeriğini POST body'siyle göndermek gerektiğinden frontend tarafında `fetch()` + `ReadableStream` kullanılır.
:::

---

## Çoklu Provider Desteği

Kullanılacak AI sağlayıcısı, `AgentConfig.model` alanının ön ekinden otomatik belirlenir:

| Model Ön Eki | Provider | SDK |
|---|---|---|
| `gemini-*` | Google | `google-genai` v2.7 |
| `claude-*` | Anthropic | `anthropic` |
| `gpt-*`, `o1-*`, `o3-*` | OpenAI | planlanıyor |

```python
def detect_provider(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("gemini"):            return "google"
    if m.startswith("claude"):            return "anthropic"
    if m.startswith(("gpt", "o1", "o3")): return "openai"
    return "google"  # varsayılan
```

Her provider için ilgili SDK adaptörü devreye girer; araç çağrısı formatları (Gemini `FunctionDeclaration`, Anthropic `tools`, OpenAI `functions`) otomatik dönüştürülür.

---

## Agentic Döngü

Her mesaj için en fazla **8 iterasyon** çalışır. Her iterasyonda model metin üretir ya da araç çağırır; araç varsa sonuç bir sonraki iterasyona bağlam olarak eklenir.

```
Kullanıcı mesajı
       │
   LLM çağrısı  (asyncio.to_thread)
       │
  ┌────┴────────────────┐
  │                     │
Metin çıktısı     Araç çağrısı(ları)
 → text olayı      → tool_call olayı
                         │
                  execute_skill()
                         │
                  tool_result olayı
                         │
                 Bağlam güncellendi
                 iterasyon < 8?
                  ├─ Evet → LLM çağrısı
                  └─ Hayır → done olayı
```

:::note asyncio.to_thread
Google ve Anthropic SDK'ları senkron çağrı kullandığından bu çağrılar `asyncio.to_thread` içinde sarılır; FastAPI event loop'u bloke edilmez.
:::

---

## Sistem Prompt Yapısı

`build_system_prompt()` her mesaj başında ajanın kimliğini, departman hedeflerini ve politikalarını birleştirir:

```
You are {person.name}.
Title: {person.title}
Department: {dept.name}

Department Goals:
{dept.goals}

Policies you must follow:
  - {policy_1}
  - ...

Available tools/skills: web_search, ...
```

Politikalar araç tanımına değil sistem prompt'una gömülür; bu sayede tüm provider API'leriyle uyumlu kalınır ve model kuralları doğal dil anlayışıyla yorumlar.

---

## DB Oturumu Yönetimi

Uzun süren LLM çağrıları sırasında SQLite bağlantısının açık tutulmaması için üç aşamalı desen uygulanır:

```python
# 1) Veriyi yükle, kullanıcı mesajını kaydet, DB'yi KAPAT
with get_session() as session:
    ...
    session.commit()

# 2) DB kapalıyken LLM akışı çalışır
async for event in agentic_loop():
    yield event

# 3) Akış bittikten sonra asistan mesajını kaydet
with get_session() as session:
    session.add(asst_msg)
    session.commit()
```

---

## Yerleşik Araçlar (Builtin Skills)

Harici bağlantı gerektirmeyen platform içi araçlar:

| Araç | Durum | Açıklama |
|---|---|---|
| `web_search` | Aktif | DuckDuckGo Instant Answer API |
| `text_to_chart` | Yer tutucu | Grafik tanımı oluşturma (F7'de tamamlanacak) |
| `code_execution` | Ertelenmiş | Python sandbox (F7+) |
| `delegate_to_agent` | Planlanıyor | A2A talebi oluşturma |

---

## İlgili Belgeler

- [Agent Runtime Mimarisi (teknik detay)](../architecture/runtime.md)
- [Skill Tipleri](../architecture/skill-types.md)
- [İşler Sayfası — Kullanım](./chat-ui.md)
- [A2A Delegasyon](./a2a-delegation.md)
