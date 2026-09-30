---
sidebar_position: 2
---

# Çalışma Alanı ve Senkronizasyon

Her insan personel için **bir çalışma alanı** vardır (ADR-0018). Kişinin tek ajanı bu alanın **içinde** çalışır; başlattığı alt ajanlar da öyle.

## Yaşam döngüsü

`creating → running ⇄ suspended`, ayrıca `failed` ve `deleted`.

- `suspended`: ev hacmi (volume) korunur, kapsayıcı durdurulur. `resume` kapsayıcıyı başlatır ve hâlâ çalışan `tmux` oturumuna yeniden bağlanır.
- `DELETE`: kapsayıcı silinir, hacim **7 gün** saklanır, sonra temizlenir. Yönetici bu süre içinde geri alabilir.
- Boşta kalma: bağlı istemci ve çalışan ajan turu yoksa `idle_minutes` (varsayılan 30, şirket başına) sonra askıya alınır. Çalışan tur veya zamanlanmış akış askıya almayı engeller.

## Kim kapsayıcı başlatır

Yalnızca ayrı bir **`workspace-controller`** servisi kapsayıcı çalışma zamanına erişir. Backend `docker.sock` bağlamaz; bir API hatası sunucuda root yetkisine dönüşmesin diye. Backend, `WorkspaceRuntime` arayüzü üzerinden (`create`, `start`, `stop`, `remove`, `attach`, `status`, `list_files`) ortak sırla konuşur (`WORKSPACE_CONTROLLER_URL`, `WORKSPACE_CONTROLLER_SECRET`).

> **Bugünkü durum:** arayüzün yalnızca test amaçlı `FakeRuntime` gerçeklemesi vardır (`WORKSPACE_RUNTIME=fake`). Gerçek denetleyici (Docker veya worker düğümü, boşta askıya alma, kapasite modeli) henüz yazılmadı; sözleşme ADR-0018'de yazılıdır.

## API

| İstek | Amaç |
|---|---|
| `POST /workspaces` | Oluştur (kişi başına idempotent) |
| `GET /workspaces/me` | Kendi çalışma alanım ve durumu |
| `GET /workspaces` | Liste — yönetici/admin, kendi şirketi |
| `POST /workspaces/{id}/resume` · `/suspend` | Sürdür / askıya al |
| `DELETE /workspaces/{id}` | Sil (hacim 7 gün) |
| `POST /workspaces/{id}/attach-ticket` | Tek kullanımlık bağlanma bileti (~30 sn) |
| `GET /workspaces/{id}/files?since=` | Dosya manifesti (yol, boyut, sha256, mtime); yalnızca değişenler |
| `GET/PUT /workspaces/{id}/files/{path}` | Dosya indir / `/workspace/in` içine yükle |

Kişi yalnızca kendi çalışma alanını yönetir; yöneticiler şirketleri içinde listeler, askıya alır ve siler. Her yaşam döngüsü çağrısı denetim kaydına yazılır.

## Bağlanma (WebSocket)

İstemci önce normal token'ı ile `attach-ticket` alır; URL'ye uzun ömürlü token konmaz (URL'ler proxy günlüklerine düşer). İkili çerçeveler ham PTY baytlarıdır; metin çerçeveleri JSON kontrol mesajlarıdır (`resize`, `ping`, `exit`). Bağlantı kopması ajanı öldürmez, yalnızca ayırır.

## Yerel klasör: `fab sync`

Kişinin bilgisayarındaki bir klasör (ör. Masaüstü) sunucudaki çalışma alanıyla `fab` tarafından eşitlenir:

- Ajanın ürettiği her şey (`/workspace/out`) klasöre iner.
- Ajan her oturum sonunda `summaries/YYYY-MM-DD-<konu>.md` biçiminde bir **oturum özeti** yazar.
- Klasörün `in/` dizinine bırakılan dosyalar çalışma alanına yüklenir.
- Çıktılar tek yönlüdür (sunucu → bilgisayar) ve adla sürümlenir (`rapor-v2.xlsx`). `fab`, kişinin yerelde düzenlediği dosyanın üzerine **asla yazmaz**; çakışmada ikisini de tutar.

## Çalışma alanı imajı

`sandbox/workspace/` altında ilk sürüm: LibreOffice, PDF araçları ve headless Chromium; `sandbox/` ile aynı sertleştirme (root olmayan kullanıcı, varsayılan-reddet çıkış, ana makine bağlaması yok). **Docker'da henüz çalıştırılmadı.**
