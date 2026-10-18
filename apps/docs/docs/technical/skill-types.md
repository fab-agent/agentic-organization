---
sidebar_position: 3
---

# Yetenek Türleri (Teknik)

Bir `Skill` kaydı `skill_type` ve türe özgü `config_json` taşır. Bu sayfa her türün gerçek davranışını anlatır. İş tarafı için bkz. [Yetenekler ve Politikalar](/guide/skills-and-policies).

| Alan | Açıklama |
|---|---|
| `skill_type` | `builtin`, `mcp`, `http`, `function`, `database` |
| `config_json` | Türe özgü ayar (JSON metin) |
| `is_active` | `false` ise araç listesine girmez |
| `name` | Aracın çağrılma adı |
| `description` | Modele gösterilen açıklama |

## builtin

`config_json`: `{"function_name": "web_search"}`; verilmezse `name` kullanılır. Uygulanan araçlar:

| `function_name` | Durum |
|---|---|
| `web_search` | Çalışır: DuckDuckGo Instant Answer API'sinden ilk 5 ilgili konu; anahtar gerekmez |
| `journal_write` | Çalışır: oturum günlüğüne Markdown girişi |
| `delegate_to_agent` | Çalışır: A2A talebi açar (`to_agent_slug`, `task`, `context`); ayara `to_agent_id` yazılırsa hedef sabitlenir |
| `instagram_post`, `whatsapp_send` | Çalışır: Ayarlar → Sosyal medya'daki kimlik bilgileriyle |
| `text_to_chart` | **Yer tutucu:** metin döndürür, grafik üretmez |
| `code_execution` | **Ertelenmiş:** çalıştırmaz |

## mcp

HTTP üzerinden JSON-RPC 2.0. Platform `POST {url}/call` (url zaten `/call` ile bitiyorsa olduğu gibi) gönderir:

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "<skill.name>", "arguments": { }}}
```

Ayar: `url`, `auth_type` (`none` · `api_key` → `X-API-Key` · `bearer`/`oauth2` → `Authorization: Bearer`), `auth_value`, isteğe bağlı `input_schema`. Yanıttaki ilk `text` içeriği döner. Zaman aşımı 30 sn. stdio ve SSE taşımaları desteklenmez.

## http

Herhangi bir REST adresi. Ayar: `url`, `method` (`POST` varsayılan | `GET`), `headers`, isteğe bağlı `input_schema`. `GET`'te argümanlar sorgu parametresi, `POST`'ta JSON gövde olur. Zaman aşımı 30 sn.

## function

Kayda gömülü Python kodu: `{"language": "python", "code": "def run(args):\n    return str(args)"}`. `run(args: dict) -> str` tanımlamalıdır. **5 saniye** içinde bitmelidir.

:::warning Gerçek bir sandbox değildir
Kod, sunucu işlemi içinde ayrı bir iş parçacığında, **az sayıda yerleşik fonksiyonla** (`len`, `str`, `sum`, `json` …) kısıtlı bir ad alanında çalışır. Bu kısıt tam bir izolasyon sağlamaz ve zaman aşımı iş parçacığını durdurmaz. Fonksiyon yeteneğini yalnızca güvendiğiniz kişilerin yazmasına izin verin; bu tür değişiklikler değişiklik talebi akışından geçer.
:::

## database

Ayar: `{"db_id": "<bağlantı kimliği>"}`. Ajan SQL üretir; platform yalnızca `SELECT` / `WITH … SELECT` sorgularını çalıştırır ve yazma komutlarını reddeder. Şema ve açıklamalar ajana bağlam olur. Bkz. [Ayarlar → Veritabanları](/guide/settings#veritabanları).
