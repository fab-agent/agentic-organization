---
sidebar_position: 9
---

# Yönetilen opencode Yapılandırması

> ADR-0011 · `backend/api/well_known.py`, `backend/services/wellknown_sign.py`,
> `sandbox/opencode.json`

opencode'un davranışını (hangi provider, hangi plugin, hangi izinler) persona
değil **platform** belirler. Bu yapılandırma imzalı olarak sunulur ve sandbox
içinde kullanıcı ayarlarının **üstünde** yer alır.

---

## Dağıtım kanalı

| Endpoint | Açıklama |
|---|---|
| `GET /.well-known/opencode` | İmzalı yönetilen yapılandırma (JSON + imza) |
| `GET /.well-known/opencode/pubkey` | Doğrulama için Ed25519 açık anahtarı (+ `previous_key_id`) |

`3pa run` yapılandırmayı çeker, imzayı açık anahtara karşı doğrular ve sandbox
konteynerine `/etc/opencode/opencode.json` olarak yerleştirir. opencode Linux'ta
bu yolu **managed config** olarak okur (`managedConfigDir()`), yani proje veya
kullanıcı `opencode.json`'u bunu geçersiz kılamaz.

---

## İmzalama

`services/wellknown_sign.py`:

- Ed25519 anahtar çifti `data/.wellknown_ed25519` içinde.
- Kanonik JSON = `json.dumps(sort_keys=True, separators=(",",":"),
  ensure_ascii=False)` — doğrulayan taraf birebir aynı kanonikleştirmeyi
  uygulamak zorunda.
- Ham açık anahtar için SPKI öneki `302a300506032b6570032100`.

### Anahtar rotasyonu

`rotate_key()` yeni bir çift üretir; eski anahtarın kimliği `previous_key_id`
olarak yayınlanır, böylece geçiş sırasında eski imzalar da bir süre
doğrulanabilir.

---

## Yapılandırmada ne var

`sandbox/opencode.json` şablonu:

```json
{
  "plugin": ["/opt/agent-plugin/src/index.ts"],
  "instructions": ["/etc/opencode/base-prompt.md"],
  "share": "disabled",
  "provider": {
    "fabagent": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "{env:FABAGENT_BASE_URL}/v1",
        "apiKey": "{env:FABAGENT_TOKEN}"
      }
    }
  },
  "permission": {
    "webfetch": "ask",
    "bash": { "git *": "allow", "npm *": "allow", "rm *": "ask", "*": "ask" }
  }
}
```

- `plugin` — politika + denetim hook'ları zorunlu yüklenir.
- `instructions` — guardrail prompt'u (injection savunması katman 2).
- `share: disabled` — oturum paylaşımı kapalı.
- `permission` — muhafazakâr varsayılanlar; politika motoru bunun üstüne biner.

`entrypoint.sh` tüm `OPENCODE_*` ortam değişkenlerini temizlediği için bu
ayarlar ortam üzerinden bypass edilemez. Bkz. [Sandbox](./sandbox.md).

---

## Açık konular

- `OPENCODE_PERMISSION` gibi kalan bypass yüzeylerinin sertleştirilmesi +
  plugin'de runtime assert.
- Anahtar rotasyonu için operatör arayüzü.
