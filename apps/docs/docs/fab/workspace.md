---
sidebar_position: 2
---

# Çalışma Alanı ve Senkronizasyon

Her insan personel için **bir çalışma alanı** vardır (ADR-0018). Kişinin tek ajanı bu alanın **içinde** çalışır; başlattığı alt ajanlar da öyle.

## Yaşam döngüsü

`creating → running ⇄ suspended`, ayrıca `failed` ve `deleted`.

- `suspended`: ev hacmi (volume) korunur, kapsayıcı durdurulur ve eski token iptal edilir. `resume` kapsayıcıyı yeni bir token ile **yeniden oluşturur**; dosyalar ve ev dizini kalır, çalışan `tmux` oturumu kalmaz. (İstemci kopması kapsayıcıyı durdurmaz; yalnızca askıya alma durdurur.)
- `DELETE`: kapsayıcı silinir ve token iptal edilir; hacim **7 gün** saklanır, sonra 15 dakikalık bir zamanlanmış iş temizler (kapsayıcı yoksa). Yönetici bu süre içinde geri alabilir.
- Boşta kalma: otomatik askıya alma **varsayılan olarak kapalıdır** (`WORKSPACE_IDLE_SUSPEND_MINUTES` ile açılır). Çalışan bir ajan turunu veya akışı henüz ayırt edemediği için açık bırakılması çalışan işi durdurabilir; bu yüzden yalnızca dosya etkinliğine bakar. Tur/akış denetimi ve şirket başına süre planlıdır.

## Kim kapsayıcı başlatır

Yalnızca ayrı bir **`workspace-controller`** servisi kapsayıcı çalışma zamanına erişir. Backend `docker.sock` bağlamaz; bir API hatası sunucuda root yetkisine dönüşmesin diye. Backend, `WorkspaceRuntime` arayüzü üzerinden (`create`, `start`, `stop`, `remove`, `attach`, `status`, `list_files`) ortak sırla konuşur (`WORKSPACE_CONTROLLER_URL`, `WORKSPACE_CONTROLLER_SECRET`).

> **Bugünkü durum (18 Ekim 2026):** denetleyici (`workspace-controller/`) ve Docker çalışma zamanı yazıldı ve tek bir sunucuda gerçek Docker ile denendi: oluşturma, askıya alma/sürdürme (yeni token ile), silme/geri yükleme, dosya listeleme/yükleme/indirme, sıfır yetenek, kök olmayan kullanıcı, doğrudan internet yok, çıkış yalnızca filtreleyen vekilden. Henüz yok: WebSocket bağlanma, boşta askıya alma zamanlayıcısı, kapasite modeli, Docker önünde fiil filtreleyen soket vekili ve üretim dağıtımı (compose servisi).

## API

| İstek | Amaç |
|---|---|
| `POST /workspaces` | Oluştur (kişi başına idempotent) |
| `GET /workspaces/me` | Kendi çalışma alanım ve durumu |
| `GET /workspaces` | Liste — yönetici/admin, kendi şirketi |
| `POST /workspaces/{id}/resume` · `/suspend` | Sürdür / askıya al |
| `DELETE /workspaces/{id}` | Sil (hacim 7 gün) |
| `POST /workspaces/{id}/attach-ticket` | *(planlı)* Tek kullanımlık bağlanma bileti (~30 sn) |
| `GET /workspaces/{id}/files?since=` | Dosya manifesti (yol, boyut, sha256, mtime); yalnızca değişenler |
| `GET/PUT /workspaces/{id}/files/{path}` | Dosya indir / `/workspace/in` içine yükle |

Kişi yalnızca kendi çalışma alanını yönetir; yöneticiler şirketleri içinde listeler, askıya alır ve siler. Her yaşam döngüsü çağrısı denetim kaydına yazılır.

## Bağlanma (WebSocket) — **planlı, henüz yok**

Tasarım şöyledir; kod yoktur. İstemci önce normal token'ı ile `attach-ticket` alır; URL'ye uzun ömürlü token konmaz (URL'ler proxy günlüklerine düşer). İkili çerçeveler ham PTY baytlarıdır; metin çerçeveleri JSON kontrol mesajlarıdır (`resize`, `ping`, `exit`). Bağlantı kopması ajanı öldürmez, yalnızca ayırır.

## Yerel klasör: `fab sync` — ADR-0022 ile daraltıldı

ADR-0022, platformla **otomatik** eşitlemeyi kaldırdı: yerel Asistan klasörü sunucuyla otomatik eşitlenmez; dosya göndermek açık seçimle, indirmek güvenli indirmeyle yapılır. Aşağıdaki `fab sync` davranışı eski tasarımdır (dondurulmuş `packages/tui`). Kişinin bilgisayarındaki bir klasör (ör. Masaüstü) sunucudaki çalışma alanıyla `fab` tarafından eşitlenir:

- Ajanın ürettiği her şey (`/workspace/out`) klasöre iner.
- Ajan her oturum sonunda `summaries/YYYY-MM-DD-<konu>.md` biçiminde bir **oturum özeti** yazar.
- Klasörün `in/` dizinine bırakılan dosyalar çalışma alanına yüklenir.
- Çıktılar tek yönlüdür (sunucu → bilgisayar) ve adla sürümlenir (`rapor-v2.xlsx`). `fab`, kişinin yerelde düzenlediği dosyanın üzerine **asla yazmaz**; çakışmada ikisini de tutar.

## Çalışma alanı imajı

`sandbox/workspace/` altında ilk sürüm: LibreOffice, PDF araçları ve headless Chromium; `sandbox/` ile aynı sertleştirme (root olmayan kullanıcı, varsayılan-reddet çıkış, ana makine bağlaması yok). Docker'da derlendi ve çalıştırıldı (18 Ekim 2026, tek sunucu); askıya alma sonrası sürdürmede kapsayıcı yeni token ile yeniden oluşturulur, bu yüzden çalışan tmux oturumu korunmaz.
