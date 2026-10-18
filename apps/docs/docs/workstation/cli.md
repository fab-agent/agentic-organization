---
sidebar_position: 6
---

# `3pa` — İş İstasyonu CLI

> ADR-0009 · `packages/cli` (`3pa`, TypeScript/tsx)

`3pa`, geliştirici personanın iş istasyonundaki tek giriş noktasıdır: platforma
giriş yapar, opencode'u yönetilen sandbox içinde başlatır, politika ve denetim
durumunu gösterir, çalışan oturumu güvenli biçimde durdurur.

---

## Komutlar

| Komut | Açıklama |
|---|---|
| `3pa init` | Kurulum sihirbazı — backend URL'i, ön koşul kontrolü |
| `3pa login` | Persona seç, workstation token çifti al → `~/.config/3pa/session.json` |
| `3pa logout` | Yerel oturumu kapat. `--revoke`: sunucuda da iptal et |
| `3pa refresh` | Persona access token'ı yenile |
| `3pa run` | opencode'u yönetilen sandbox içinde başlat |
| `3pa policy` | Persona için etkin politika kurallarını göster |
| `3pa audit verify` | Sunucudaki denetim zincirini doğrula |
| `3pa stop` | Çalışan sandbox oturumunu durdur (imzalı komut) |
| `3pa signal <sinyal>` | Oturuma imzalı bir kontrol sinyali gönder |
| `3pa doctor` | Sandbox ön koşullarını kontrol et (Docker, ağ, imaj) |
| `3pa start` / `3pa status` | Platformu Docker ile başlat / durumunu göster |

---

## Oturum dosyası

`~/.config/3pa/session.json` — persona kimliği, access + refresh token, backend
URL. Test izolasyonu için `THREEPA_SESSION_FILE` ortam değişkeni ile
geçersiz kılınabilir. `sandbox/run.sh` bu dosyayı okur.

---

## `3pa run` ne yapar

1. Access token'ın geçerliliğini kontrol eder, gerekiyorsa `refresh` çağırır.
2. [Yönetilen yapılandırmayı](./managed-config.md) `/.well-known/opencode`'dan
   çeker ve imzasını doğrular.
3. [Sandbox](./sandbox.md) konteynerini + egress proxy'yi ayağa kaldırır;
   proje dizinini `/work` olarak bağlar.
4. opencode'u konteyner içinde başlatır — gateway provider'ı, plugin ve
   guardrail prompt'u önceden yerleştirilmiş olarak.
5. Heartbeat döngüsü: `POST /workstation/heartbeat` — durum bildirir ve
   [imzalı komut kanalını](./injection-defense.md) yoklar (ör. uzaktan `stop`).

---

## Heartbeat ve komut kanalı

`3pa` çalışırken düzenli `POST /workstation/heartbeat` gönderir. Yanıtta
bekleyen **imzalı komutlar** (`PersonaCommand`) gelir; `3pa` her birini Ed25519
ile doğrular, uygular ve `POST /workstation/commands/{id}/ack` ile onaylar.
Sahip, panelden `POST /workstation/commands` ile bir oturuma komut kuyruklayabilir
(ör. çalışan bir sandbox'ı uzaktan durdurmak).

---

## Dağıtım

`release.yml` (ADR-0012) `3pa`'yı esbuild ile tek dosyaya bundle'lar ve GitHub
Packages'a yayınlar. opencode sürümü **1.18.26**'ya sabittir — uyumluluk
matrisi: `docs/architecture/version-compat.md`.

---

## Açık konular

- `3pa update` — kendi kendini güncelleme.
- Go ile derlenmiş tek ikili `3pa` (Node bağımlılığını kaldırmak için).
