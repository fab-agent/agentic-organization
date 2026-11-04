---
sidebar_position: 3
---

# Kurulum ve Dağıtım

> ADR-0030 · ADR-0031 · ADR-0032 · ADR-0033 (hepsi "önerildi")

Kurucular **hiçbir şey indirmez**; yönetici (veya MDM) dosyaları ve SHA-256 değerlerini verir. Hepsi kullanıcının
kendi klasöründe çalışır, root/SYSTEM gerekmez.

## Kullanıcı kurucuları

| Platform | Dosya | Not |
|---|---|---|
| Linux / macOS | `installers/user/install.sh` | `--base-url`, `--root-pub`, `--cli`, `--cli-sha256`; isteğe bağlı çiftler: `--herdr-bin` + `--herdr-sha256`, `--release-pub` + `--release-url`; ayrıca `--dry-run`, `--uninstall` |
| Windows | `installers/user/windows/install.mjs` + `install.ps1` | Yükseltilmiş oturumu varsayılan reddeder (`--allow-elevated` ile açılır) |

Kurucu şunları yerleştirir: `3pa` paketi (hash denetimli), sabitlenmiş kök açık anahtarı, isteğe bağlı Herdr
ikilisi ve çalışma alanını eşitleyip Herdr'i başlatan bir `herdr-fab` başlatıcısı. Kaldırma, yalnızca kendi
yazdığı adları siler. Windows yolu CI'da Windows, Ubuntu ve macOS üzerinde test edilir.

**Windows sınırları:** ikililer ve kurucu Authenticode ile imzalı değildir; MSI ve PATH yönetimi yoktur; Herdr
uygulama klasörünün varsayılanı bir tahmindir (`--app-home` ile belirtin).

## İmzalı sürüm zinciri ve `3pa self-update`

`3pa self-update`, ayrı bir **sürüm anahtarıyla** imzalanmış sürüm bildirimini doğrulayıp yeni paketi kurar.
Sürüm anahtarı da çevrimdışıdır. Bildirimi imzalayan araç depoda vardır, ama **sürüm iş akışı henüz imzasız
`body.json` üretmez ve anahtar değişimi elle yapılır.**

## Dağıtım sözleşmesi (MDM'den bağımsız)

`installers/deploy/` klasörü, bir filo için *ne dağıtılır, nasıl çalışır, uyumlu mu, nasıl güncellenir, nasıl
geri alınır* sorularının tek cevabıdır; Intune, Jamf, Ansible veya bir oturum açma betiği aynı komutları çağırır.

- `deploy.conf`: yalnızca `KEY=VALUE` (açık anahtarlar, URL'ler, hash'ler); içinde sır olmaz, çalıştırılmaz.
- `deploy.sh|deploy.ps1 install` kullanıcı olarak çalışır (macOS'ta root ise konsol kullanıcısına geçer; Windows'ta SYSTEM reddedilir). Zaten uyumluysa hiçbir şey yapmaz.
- `check` hiçbir şeyi değiştirmez; yalnızca amaçlanan paket, giriş betikleri ve sabitlenmiş anahtarlar tam
  olarak yerindeyse 0 döner. Kendini güncelleyen filolarda `check --pins-only` kullanın.
- `install`, içeriği ayarlardakinden farklı bir **`3pa` paketinin veya Herdr ikilisinin üzerine yazmaz**
  (`--force-artifacts` açıkça ister). Giriş betikleri (`bin/3pa`, başlatıcı) ise bozulmuşsa yeniden yazılır.
- Komut bayrakları kabuğa göre değişir: `deploy.sh install --config rollout/deploy.conf`,
  PowerShell'de `deploy.ps1 install -Config rollout\deploy.conf`; `--pins-only`/`--force-artifacts` PowerShell'de
  `-PinsOnly`/`-ForceArtifacts`.

Ayrıntı: depodaki `installers/deploy/README.md`. Node.js 20+ makinede önceden bulunmalıdır.
