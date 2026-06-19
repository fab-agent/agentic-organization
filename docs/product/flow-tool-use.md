---
sidebar_position: 14
---

# Akışlarda Tool Use

Zamanlanmış akışlar (flows) artık tek turlu LLM çağrısıyla sınırlı değildir. **Anthropic** modelleri üzerinden çalışan akışlar, ajanın tanımlı skill'lerini araç olarak kullanabilir ve çok adımlı görevleri tamamlayabilir.

---

## Nasıl Çalışır?

```
Akış tetiklenir (cron)
    ↓
Ajanın aktif skill'leri yüklenir
    ↓
Skill'ler Anthropic tool definition formatına çevrilir
    ↓
LLM çağrısı yapılır (tools parametresiyle)
    ↓
LLM tool_use döndürürse → araç çalıştırılır, sonuç LLM'e gönderilir
    ↓
(maks. 8 iterasyon)
    ↓
Son metin yanıtı inbox'a iletilir
```

---

## Desteklenen Skill Türleri

| Skill Türü | Akışta Tool Use |
|---|---|
| `builtin` (web_search, text_to_chart) | ✅ Desteklenir |
| `http` (URL tanımlıysa) | ✅ Desteklenir |
| `mcp` | ⚠️ Kısmi (geliştirme aşamasında) |
| `function` | ❌ Henüz desteklenmiyor |

---

## Provider Desteği

| Provider | Tool Use |
|---|---|
| **Anthropic (Claude)** | ✅ Tam destek (multi-turn tool loop) |
| OpenAI (GPT) | ⚠️ Single-turn fallback |
| Google (Gemini) | ⚠️ Single-turn fallback |
| Mistral | ⚠️ Single-turn fallback |

Tool use yalnızca Anthropic modelleri için etkindir. Diğer sağlayıcılarda akış tek turlu çalışmaya devam eder.

---

## İterasyon Limiti

Sonsuz döngü riskine karşı, bir akış çalışmasında **maksimum 8 tool çağrısı** yapılabilir. Bu sınıra ulaşıldığında mevcut yanıt döndürülür.

---

## Örnek: Web Araması Yapan Akış

**Ajan**: `market-analyst` — skill: `web_search (builtin)`

**Akış promptu**:
```
Bugünün yapay zeka sektörü haberlerini araştır ve önemli gelişmeleri özetle.
```

**Çalışma adımları**:
1. LLM `web_search` aracını çağırır: `{"query": "AI news today"}`
2. DuckDuckGo araması yapılır, sonuç LLM'e döner
3. LLM ikinci bir arama yapabilir veya özet üretir
4. Final metin inbox'a düşer

---

## Skill Yapılandırması

Akışta kullanılacak skill'in **aktif** olması gerekir. `is_active: false` skill'ler tool definition listesine eklenmez.

Builtin skill için `config_json`:
```json
{
  "function_name": "web_search"
}
```

HTTP skill için `config_json`:
```json
{
  "url": "https://api.example.com/data",
  "method": "POST"
}
```
