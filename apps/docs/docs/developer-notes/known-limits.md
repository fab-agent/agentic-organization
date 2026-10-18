---
sidebar_position: 2
---

# Bilinen Sınırlar ve Açık İşler

Bu sayfa, dokümantasyonu koda karşı doğrularken bulunan **gerçek eksikleri** ve henüz yapılmamış işleri listeler. Dürüst bir "ürün bugün nerede" tablosu olması için tutulur. Bir madde çözüldüğünde buradan silinir.

*Son doğrulama: 18 Ekim 2026.*

## Ürünle ilgili

| Konu | Durum | Etkisi |
|---|---|---|
| **Uygulama içi yedekleme yalnızca SQLite** | `api/backup.py` yalnızca SQLite dosyasını yedekler. Tüm Docker kurulumları PostgreSQL kullanır | PostgreSQL'de Ayarlar → Yedekle çalışmaz; `pg_dump` ayrıca gerekir |
| **`ENCRYPTION_KEY` kullanılmıyor** | `.env.example` ve `setup-env.sh` üretir, kod okumaz. Gerçek anahtar `data/.secret` | Yanıltıcı; yedeğe `data/.secret` dahil edilmeli |
| **Rol kontrolü kısmen yalnızca arayüzde** | Davet/rol atama, değişiklik talebi onayı ve eval API rol ve kapsam denetler; birçok başka API (departman, personel, akış…) hâlâ yalnızca şirket üyeliğini kontrol eder. Personel yapısı yönetici rolü, ajan ayarları (model, durum, yetenek, politika bağı) şirket genelindeki yönetici/kurucu ya da henüz `draft` olan ajan için bölüm yöneticisi gerektirir | API'ye doğrudan erişimde yetki yükseltme riski |
| **Gelen Kutusu'na kenar çubuğunda bağlantı yok** | `/inbox` yalnızca `user` rolünde girişte açılır | Diğer roller adresi elle yazar |
| **Yönetici şifre sıfırlama düğmesi yok** | `POST /auth/reset/{id}` var, arayüzde yok | Yalnızca API ile |
| **Politika motoru kipi için arayüz yok** | `PUT /policies/config` ile `off/dry_run/enforce` | Zorlama için API gerekir |
| **A2A talepleri bildirim üretmiyor** | Gelen Kutusu/Telegram bildirimi yok (Telegram botundaki `/onaylar` hariç) | Onaylayan bekleyen işi fark etmeyebilir |
| **`text_to_chart` yer tutucu, `code_execution` ertelenmiş** | Araç listesinde "Grafik Üretimi" görünür ama grafik üretmez | Beklenti yönetimi |
| **Akışlarda araç kullanımı yalnızca Anthropic protokolü** | Diğer sağlayıcılarda araçsız tek çağrı | Akışlar bazı modellerde araç kullanamaz |
| **`function` yeteneği tam izole değil** | Kısıtlı ad alanı + zaman aşımı, süreç izolasyonu yok | Güvenilmeyen kod çalıştırılmamalı |
| **Git: yalnızca GitHub** | Değişiklik talebi commit'i GitHub dışında hata verir; arayüz GitLab/Gitea'yı da sunar | Yerel git planlandı |

## fab (departman çalışma alanı)

| Konu | Durum |
|---|---|
| Gerçek çalışma alanı çalışma zamanı | Yok; yalnızca test için `FakeRuntime` |
| Çalışma alanı imajı | Docker'da çalıştırılmadı |
| Puanlama ve kalibrasyon | Canlı Jev ile ölçülmedi; eşikler öneridir |
| Süzme | Yalnızca biçime bakar; isim/adres tanımaz |
| Hukuki inceleme | Puanlama ve yöneticiyle paylaşım açılmadan önce şart (KVKK/GDPR) |
| Eksik `fab` ekranları | Rubrik görünümü, birim bulguları, paylaşılan sinyaller, itirazı çözen kişi |

Ayrıntı: [fab → Yönetici Rehberi](/fab/enablement).

## Dokümantasyon ve süreç

| Konu | Durum |
|---|---|
| `docs/ROADMAP.md` | Güncel (30 Eylül 2026) |
| `NOTLAR.md` (depoda) | Haziran 2026'dan kalma; SQLite, "denetim kaydı yok" gibi artık geçerli olmayan maddeler içerir. Güncel özet [Geliştirici Notları](/developer-notes/overview)'ndadır |
