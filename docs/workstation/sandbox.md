---
sidebar_position: 7
---

# İzole Çalıştırma Ortamı (Sandbox)

> ADR-0002 · `sandbox/` (`Dockerfile`, `compose.yaml`, `entrypoint.sh`,
> `run.sh`, `egress/`)

opencode iş istasyonunda **doğrudan** değil, zorunlu bir yerel sandbox
konteyneri içinde çalışır. Ajanın etki alanı bu konteynerdir: dosya erişimi
bağlanan proje dizinine, ağ erişimi tek bir filtreleyen proxy'ye sınırlıdır.

---

## Ağ topolojisi

```
  sandbox konteyneri            egress konteyneri
  ┌───────────────┐   internal  ┌──────────────┐  external
  │  opencode     │────ağ──────►│  tinyproxy   │──────────► internet
  │  (no route    │             │  allowlist   │            (yalnız izinli
  │   to internet)│             └──────────────┘             hostlar)
  └───────────────┘
```

- `sandbox`, `internal: true` bir Docker ağındadır — internete **rota yoktur**.
- Tek çıkış `egress`: `egress/base-allowlist.txt` + `$EGRESS_ALLOWLIST` +
  `$FABAGENT_BASE_URL`'deki gateway host'u dışındaki her şeyi reddeder.
- `HTTP(S)_PROXY` ortam değişkenleri ayarlıdır; **ama** bir araç bunları
  yok saysa bile ağın başka rotası olmadığı için hiçbir yere ulaşamaz.

`egress` proxy `tinyproxy` ile çalışır: `FilterDefaultDeny On` +
genişletilmiş regex allowlist (`FilterExtended On`).

---

## İzolasyon sıkılaştırması

`compose.yaml` içindeki `sandbox` servisi:

| Ayar | Değer | Neden |
|---|---|---|
| `cap_drop` | `ALL` | Hiçbir Linux capability yok |
| `security_opt` | `no-new-privileges:true` | setuid ile yetki yükseltme yok |
| `pids_limit` | `512` | Fork bomb sınırı |
| `mem_limit` | `2g` | Bellek tavanı |
| `cpus` | `2.0` | CPU tavanı |
| `volumes` | `${PROJECT_DIR}:/work` | Yalnız proje dizini görünür |

`entrypoint.sh`, opencode başlamadan önce tüm `OPENCODE_*` ortam
değişkenlerini **temizler** — böylece bir çağıran, ortam değişkeni enjekte
ederek [yönetilen yapılandırmayı](./managed-config.md) veya izin ayarlarını
geçersiz kılamaz.

---

## Konteyner içeriği

| Yol | İçerik |
|---|---|
| `/opt/agent-plugin/src/index.ts` | opencode plugin — politika + denetim hook'ları |
| `/etc/opencode/opencode.json` | Yönetilen yapılandırma (gateway provider, izinler) |
| `/etc/opencode/base-prompt.md` | Kalıcı guardrail sistem direktifleri |
| `/work` | Bağlanan proje dizini |

Model önceden ayarlıdır: `OPENCODE_MODEL=${FABAGENT_MODEL:-fabagent/qwen-turbo}`,
provider `fabagent` → `{FABAGENT_BASE_URL}/v1`, apiKey `{FABAGENT_TOKEN}`.

---

## Çalıştırma

Normalde `3pa run` orkestre eder. Doğrudan:

```bash
FABAGENT_BASE_URL=https://agent.example.com \
FABAGENT_TOKEN=<persona token> \
PROJECT_DIR=~/code/my-project \
docker compose -f sandbox/compose.yaml run --rm sandbox
```

---

## Açık konular

- Salt-okunur root dosya sistemi.
- macOS için hafif VM izolasyonu (konteyner yerine).
