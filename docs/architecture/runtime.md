---
sidebar_position: 3
---

# Agent Runtime Mimarisi (F6B)

Bu belge, 3PA'nın agent çalıştırma katmanını açıklamaktadır: sistem prompt'u oluşturma, araç tanım hattı, çoklu provider yönlendirmesi, SSE akış tasarımı ve agentic döngü.

---

## Genel Bakış

Bir kullanıcı agent'ına mesaj gönderdiğinde şu adımlar sırayla işlenir:

1. `AgentSession` ve ilgili `AgentConfig` + `Skill` kayıtları DB'den yüklenir.
2. Sistem prompt'u ve araç tanımları oluşturulur.
3. DB oturumu **kapatılır** — uzun süren LLM çağrıları boyunca bağlantı tutulmaz.
4. Provider'a göre uygun adapter seçilir ve agentic döngü başlar.
5. SSE olayları (`text`, `tool_call`, `tool_result`, `done`) HTTP akışı olarak gönderilir.
6. Döngü sonunda asistan mesajı DB'ye kaydedilir.

---

## Sistem Prompt Oluşturma

`build_system_prompt()` fonksiyonu her mesaj başında çalışır ve agent'ın kimliğini, bağlamını ve kısıtlamalarını düz metin olarak birleştirir.

```
You are {person.name}.
Title: {person.title}
Role: {person.role}
Department: {dept.name}

Department Goals:
{dept.goals}

Policies you must follow:
  - {policy_1}
  - {policy_2}

Available tools/skills: web_search, send_email

Respond helpfully and concisely. Use tools when they would help.
```

### Tasarım Kararları

:::note Politikalar sistem prompt'unda neden düz metin?
Policy'ler, departman düzeyinde tanımlı kısa kural dizileridir. Bunları `tools=[]` parametresine değil sistem prompt'una yerleştirmek iki avantaj sağlar: (1) Her LLM API'siyle uyumlu, provider'a özgü politika alanı gerektirmez. (2) Model, kuralları doğal dil anlayışıyla yorumlar ve katı ayrıştırma hataları oluşmaz.
:::

:::note Araçlar neden ayrı `tools` parametresinde?
Araçlar yapılandırılmış çağrı gerektirdiği için (`name`, `args`, `parameters` şeması) her provider'ın yerleşik araç çağrısı mekanizması kullanılır. Bu sayede model doğru JSON üretir ve platform tool_use/function_call akışını güvenle ayrıştırabilir.
:::

---

## Araç Tanım Hattı

`build_tool_definitions()` her aktif `Skill` kaydını provider'a gönderilebilecek bir işlev bildirimine dönüştürür.

```
Skill (DB)
  ├── skill_type: "builtin" | "mcp" | "http" | "function"
  ├── config_json: {...}
  └── is_active: true
          │
          ▼
  tool_def (dict)
  ├── name: "web_search"
  ├── description: "..."
  ├── parameters: {type: object, properties: {...}}
  ├── _skill_id: "uuid"
  ├── _skill_type: "builtin"
  └── _config: {function_name: "web_search"}
          │
          ▼ (Google Gemini için)
  types.FunctionDeclaration(
      name=..., description=...,
      parameters=types.Schema(...)
  )
```

`_skill_id`, `_skill_type`, `_config` alanları yalnızca platform içi yönlendirme için kullanılır; LLM API'sine **gönderilmez**.

---

## Çoklu Provider Yönlendirmesi

Provider, `AgentConfig.model` alanının ön ekine göre belirlenir.

| Model Ön Eki | Provider | SDK |
|---|---|---|
| `gemini-*` | Google | `google-genai` v2.7 (`from google import genai`) |
| `claude-*` | Anthropic | `anthropic` |
| `gpt-*`, `o1-*`, `o3-*` | OpenAI | (planlanıyor) |

:::note `model` vs `model_version` alanı
`AgentConfig.model_version` "4.6" gibi kısa bir etiket olabilir ve provider tespiti için yetersizdir. Provider tespitinde her zaman `cfg.model` tam adı (`gemini-2.0-flash`, `claude-sonnet-4-6`, vb.) kullanılır.
:::

```python
def detect_provider(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("gemini"):   return "google"
    if m.startswith("claude"):   return "anthropic"
    if m.startswith(("gpt", "o1", "o3")): return "openai"
    return "google"  # varsayılan
```

---

## SSE Akış Tasarımı

### Endpoint

```
POST /sessions/{session_id}/messages
Content-Type: application/json
Accept: text/event-stream

{"content": "Bugünkü satış rakamlarını göster"}
```

Yanıt: `Content-Type: text/event-stream`

### Neden WebSocket Değil SSE?

:::tip SSE seçim gerekçesi
Agent'ın istemciye iletmesi gereken veri akışı tek yönlüdür (sunucu → istemci). SSE, HTTP-native'dir, proxy ve load balancer uyumluluğu yüksektir. WebSocket el sıkışması ve ikili çerçeve protokolü bu kullanım için gereksiz karmaşıklık ekler. EventSource API yerine `fetch() + ReadableStream` kullanılır çünkü EventSource, POST body'si desteklemiyor.
:::

### SSE Olay Türleri

| `type` | Açıklama | Örnek |
|---|---|---|
| `text` | LLM'den gelen metin parçası | `{"type":"text","content":"Merhaba..."}` |
| `tool_call` | Model bir araç çağırdı | `{"type":"tool_call","name":"web_search","args":{"query":"..."}}` |
| `tool_result` | Araç sonucu döndü | `{"type":"tool_result","name":"web_search","result":"..."}` |
| `done` | Tüm mesaj tamamlandı, DB'ye kaydedildi | `{"type":"done","message_id":"uuid"}` |
| `error` | Çalışma zamanı hatası | `{"type":"error","message":"No active API key..."}` |
| `stream_end` | Akış kapanıyor (hata olsa da gönderilir) | `{"type":"stream_end"}` |

Her olay `data: {json}\n\n` formatında iletilir.

### Frontend Entegrasyonu

```typescript
const resp = await fetch(`/sessions/${sessionId}/messages`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ content: userInput }),
});

const reader = resp.body!.getReader();
const decoder = new TextDecoder();

while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  const lines = decoder.decode(value).split("\n");
  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const event = JSON.parse(line.slice(6));
    // event.type: "text" | "tool_call" | "tool_result" | "done" | "error" | "stream_end"
  }
}
```

---

## Agentic Döngü

Her mesaj için en fazla **8 iterasyon** çalışır. Her iterasyonda model metin üretir veya araç çağırır; araç çağrısı varsa sonuçlar bir sonraki iterasyona bağlam olarak eklenir.

```
┌─────────────────────────────────────┐
│        Kullanıcı mesajı             │
└──────────────┬──────────────────────┘
               │
        ┌──────▼──────┐
        │  LLM çağrısı │  (asyncio.to_thread — senkron SDK)
        └──────┬───────┘
               │
     ┌─────────┴──────────┐
     │                    │
  Metin çıktısı     Araç çağrısı(ları)
  → text olayı      → tool_call olayı
                         │
                  ┌──────▼──────┐
                  │ execute_skill│
                  └──────┬───────┘
                         │
                  tool_result olayı
                         │
               Bağlam güncellendi
               (iterasyon + 1)
                         │
              iterasyon < 8?
               ├── Evet → LLM çağrısı
               └── Hayır → done olayı
```

:::note `asyncio.to_thread` kullanımı
Google Gemini ve Anthropic SDK'ları şu an senkron `generate_content` / `messages.create` çağrısı ile kullanılmaktadır. Bu çağrılar `asyncio.to_thread` içinde sarılarak FastAPI'nin event loop'u bloke edilmemektedir. Gerçek karakter düzeyinde streaming ileriki iterasyona bırakılmıştır.
:::

---

## DB Oturumu Yönetimi

```python
# 1) Veriyi yükle, kullanıcı mesajını kaydet, DB oturumunu KAPAT
with get_session() as session:
    ...
    session.commit()

# 2) DB oturumu kapalıyken LLM streaming çalışır (sn ~ dk arası)
async for event in gen:
    yield event

# 3) Akış bittikten sonra yeni oturum aç, asistan mesajını kaydet
with get_session() as session:
    session.add(asst_msg)
    session.commit()
```

Bu desen, uzun süren LLM çağrıları sırasında SQLite bağlantısının açık tutulmasını engelleyen en önemli mimari karardır.

---

## MCP Transportları

| Transport | Durum | Notlar |
|---|---|---|
| SSE / HTTP JSON-RPC | Destekleniyor | `call_mcp_sse_tool()` — POST `/call` endpoint'ine JSON-RPC 2.0 |
| HTTP doğrudan | Destekleniyor | `call_http_tool()` — GET veya POST, args query/body olarak geçer |
| stdio | Ertelenmiş | Süreç izolasyonu gerektirdiği için F7+'a alındı |

MCP sunucuları JSON-RPC 2.0 protokolü ile `/call` endpoint'ini açmalıdır:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "tool_adı",
    "arguments": { "key": "value" }
  }
}
```

---

## Bağlam Penceresi Değerlendirmeleri

| İçerik | Nerede | Yaklaşık Boyut |
|---|---|---|
| Sistem prompt (kimlik + politikalar) | `system_instruction` | ~200–500 token |
| Araç tanımları | `tools=[]` parametresi | ~100–300 token / araç |
| Konuşma geçmişi | `contents` listesi | Tüm önceki mesajlar |
| Araç sonuçları | `function_response` parçaları | Araç yanıtına göre değişken |

Politikalar kısa kural dizileri olduğu için token tüketimi düşüktür. Yüksek miktarda araç ve uzun geçmişin bir arada bulunduğu oturumlar model bağlam limitine yaklaşabilir; bu durum ileriki fazlarda konuşma özetleme ile yönetilecektir.

---

## İlgili Belgeler

- [Skill Tipleri](./skill-types.md)
- [Provider Anahtar Yönetimi](./provider-key-management.md)
- [A2A Mimarisi](../product/a2a-architecture.md)
