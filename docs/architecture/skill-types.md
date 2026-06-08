---
sidebar_position: 4
---

# Skill Tipleri

Bu belge, 3PA'da tanımlı dört skill tipini, her tipin `config_json` şemasını ve çalışma zamanı davranışlarını açıklamaktadır.

---

## Genel Bakış

Her `Skill` kaydı şu alanlara sahiptir:

| Alan | Tür | Açıklama |
|---|---|---|
| `skill_type` | `string` | `builtin` \| `mcp` \| `http` \| `function` |
| `config_json` | `string` (JSON) | Tipe özgü bağlantı/çalıştırma yapılandırması |
| `is_active` | `boolean` | `false` ise araç tanım listesine dahil edilmez |
| `name` | `string` | Aracın çağrılacağı tanımlayıcı (boşluklar `_` olur) |
| `version` | `string` | Semantik sürüm (`1.0.0`) |
| `description` | `string` | LLM'e gösterilen araç açıklaması |

---

## builtin — Yerleşik Yetenekler

Platform içinde kodlanmış, harici bağlantı gerektirmeyen araçlar.

### Desteklenen Fonksiyonlar

| `function_name` | Açıklama | Durum |
|---|---|---|
| `web_search` | DuckDuckGo arama API'si ile web araması | Aktif |
| `text_to_chart` | Veriyi grafik tanımına dönüştürme | Yer tutucu |
| `code_execution` | Python kodu çalıştırma | Ertelenmiş |

### config_json Şeması

```json
{
  "function_name": "web_search"
}
```

`function_name` belirtilmezse `skill.name` kullanılır.

### Parametre Şemaları (Otomatik)

`web_search`:
```json
{
  "type": "object",
  "properties": {
    "query": { "type": "string", "description": "Search query" }
  },
  "required": ["query"]
}
```

`text_to_chart`:
```json
{
  "type": "object",
  "properties": {
    "data":       { "type": "string", "description": "Data as JSON or CSV string" },
    "chart_type": { "type": "string", "description": "bar, line, pie, etc." },
    "title":      { "type": "string" }
  },
  "required": ["data"]
}
```

`code_execution`:
```json
{
  "type": "object",
  "properties": {
    "code":     { "type": "string", "description": "Python code to execute" },
    "language": { "type": "string", "description": "Programming language" }
  },
  "required": ["code"]
}
```

### web_search Uygulaması

```
DuckDuckGo Instant Answer API
GET https://api.duckduckgo.com/?format=json&no_html=1&q={query}

Yanıttan RelatedTopics[0..4].Text alanları alınır, satır satır döndürülür.
API anahtarı gerekmez.
```

:::note text_to_chart ve code_execution
`text_to_chart` şu an yer tutucu döndürmektedir. `code_execution` ise süreç izolasyonu gerektirdiğinden henüz etkin değildir.
:::

---

## mcp — Model Context Protocol

MCP standardını uygulayan harici araç sunucularına HTTP üzerinden JSON-RPC 2.0 ile bağlanan skill tipi.

### config_json Şeması

```json
{
  "url":        "https://tools.example.com/mcp",
  "transport":  "http",
  "auth_type":  "api_key",
  "auth_value": "sk-..."
}
```

| Alan | Zorunlu | Açıklama |
|---|---|---|
| `url` | Evet | MCP sunucusunun temel URL'i |
| `transport` | Hayır | `"http"` (varsayılan) \| `"sse"` (planlanıyor) |
| `auth_type` | Hayır | `"none"` \| `"api_key"` \| `"bearer"` \| `"oauth2"` |
| `auth_value` | Koşullu | `auth_type` `"none"` değilse gerekli |
| `input_schema` | Hayır | JSON Schema — belirtilmezse tek `input: string` parametresi kullanılır |

### Çalışma Zamanı Akışı

```
platform → POST {url}/call
  {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "{skill.name}",
      "arguments": { ...model_args... }
    }
  }

MCP sunucu yanıtı:
  {
    "result": {
      "content": [{ "type": "text", "text": "sonuç metni" }]
    }
  }
```

Kimlik doğrulama başlıkları:

| `auth_type` | HTTP Başlığı |
|---|---|
| `api_key` | `X-API-Key: {auth_value}` |
| `bearer` / `oauth2` | `Authorization: Bearer {auth_value}` |
| `none` | — |

:::note stdio desteği
MCP stdio transportu süreç izolasyonu gerektirdiğinden şu an desteklenmemektedir. Yalnızca HTTP tabanlı MCP sunucuları kullanılabilir.
:::

---

## http — Doğrudan HTTP Araçları

Herhangi bir REST endpoint'ini araç olarak kullanan skill tipi. MCP protokolü gerektirmez.

### config_json Şeması

```json
{
  "url":    "https://api.example.com/tool",
  "method": "POST",
  "headers": {
    "Authorization": "Bearer sk-...",
    "Content-Type":  "application/json"
  },
  "input_schema": {
    "type": "object",
    "properties": {
      "query": { "type": "string" }
    },
    "required": ["query"]
  }
}
```

| Alan | Zorunlu | Açıklama |
|---|---|---|
| `url` | Evet | Araç endpoint'inin tam URL'i |
| `method` | Hayır | `"POST"` (varsayılan) \| `"GET"` |
| `headers` | Hayır | Sabit HTTP başlıkları (kimlik doğrulama dahil) |
| `input_schema` | Hayır | JSON Schema — belirtilmezse tek `input: string` parametresi kullanılır |

### Çalışma Zamanı Davranışı

- `GET`: Argümanlar query parametresi olarak eklenir.
- `POST`: Argümanlar JSON body olarak gönderilir.
- Yanıt JSON ise parse edilir, değilse düz metin olarak döndürülür.

---

## function — Python Fonksiyonu

Agent'a özgü Python kodu doğrudan kayıt içinde tanımlanabilen skill tipi.

:::note Mevcut durum
`function` tipi için araç tanımı ve DB kaydı desteklenmektedir, ancak **kod çalıştırma henüz etkin değildir**. Çalışma zamanında `[Function execution deferred — {skill.name}]` mesajı döndürülür. Sandbox çalışma ortamı ilerleyen dönemde eklenecektir.
:::

### config_json Şeması

```json
{
  "language": "python",
  "code": "def run(params):\n    return params['x'] * 2"
}
```

| Alan | Açıklama |
|---|---|
| `language` | Şimdilik yalnızca `"python"` |
| `code` | Çalıştırılacak fonksiyon tanımı (`run(params)` imzasını içermeli) |

### Parametre Şeması (Otomatik)

```json
{
  "type": "object",
  "properties": {
    "params": {
      "type": "string",
      "description": "JSON params string"
    }
  },
  "required": []
}
```

---

## Skill Seçim Rehberi

| İhtiyaç | Önerilen Tip |
|---|---|
| Web araması, grafik oluşturma, kod çalıştırma | `builtin` |
| MCP standartlı harici araç sunucusu | `mcp` |
| Özel REST API veya webhook | `http` |
| Agent'a özel mantık (kısa Python) | `function` |

---

## İlgili Belgeler

- [Agent Runtime Mimarisi](./runtime.md)
- [Policy & Skills (Ürün)](../product/policy-and-skills.md)
