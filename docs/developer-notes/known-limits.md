---
sidebar_position: 2
---

# Bilinen Sınırlar ve Açık İşler

Bu sayfa, dokümantasyonu koda karşı doğrularken bulunan **gerçek eksikleri** ve henüz yapılmamış işleri listeler. Dürüst bir "ürün bugün nerede" tablosu olması için tutulur. Bir madde çözüldüğünde buradan silinir.

*Son doğrulama: 1 Ekim 2026, `main` @ `319f78b`.*

## Ürünle ilgili

| Konu | Durum | Etkisi |
|---|---|---|
| **Uygulama içi yedekleme yalnızca SQLite** | `api/backup.py` yalnızca SQLite dosyasını yedekler. Tüm Docker kurulumları PostgreSQL kullanır | PostgreSQL'de Ayarlar → Yedekle çalışmaz; `pg_dump` ayrıca gerekir |
| **`ENCRYPTION_KEY` kullanılmıyor** | `.env.example` ve `setup-env.sh` üretir, kod okumaz. Gerçek anahtar `data/.secret` | Yanıltıcı; yedeğe `data/.secret` dahil edilmeli |
| **Rol kontrolü kısmen yalnızca arayüzde** | Birçok API (departman, personel, akış…) yalnızca şirket üyeliğini kontrol eder; `require_manager` herhangi bir şirketteki rolü arar | API'ye doğrudan erişimde yetki yükseltme riski |
| **Gelen Kutusu'na kenar çubuğunda bağlantı yok** | `/inbox` yalnızca `user` rolünde girişte açılır | Diğer roller adresi elle yazar |
| **Yönetici şifre sıfırlama düğmesi yok** | `POST /auth/reset/{id}` var, arayüzde yok | Yalnızca API ile |
| **Politika motoru kipi için arayüz yok** | `PUT /policies/config` ile `off/dry_run/enforce` | Zorlama için API gerekir |
| **A2A talepleri bildirim üretmiyor** | Gelen Kutusu/Telegram bildirimi yok (Telegram botundaki `/onaylar` hariç) | Onaylayan bekleyen işi fark etmeyebilir |
| **`text_to_chart` yer tutucu, `code_execution` ertelenmiş** | Araç listesinde "Grafik Üretimi" görünür ama grafik üretmez | Beklenti yönetimi |
| **Akışlarda araç kullanımı yalnızca Anthropic protokolü** | Diğer sağlayıcılarda araçsız tek çağrı | Akışlar bazı modellerde araç kullanamaz |
| **`function` yeteneği tam izole değil** | Kısıtlı ad alanı + zaman aşımı, süreç izolasyonu yok | Güvenilmeyen kod çalıştırılmamalı |
| **Git: yalnızca GitHub** | Değişiklik talebi commit'i GitHub dışında hata verir; arayüz GitLab/Gitea'yı da sunar | Yerel git planlandı |
| **Sürüm numarası** | `backend/version.py` hâlâ `1.1.2`; dokümantasyon sürümü v1.3 diyor | Panel'deki "yeni sürüm" kontrolü yanıltıcı olabilir |
| **Lisans anlatımı tutarsız** | `LICENSE` dosyası **düz MIT** (18 Temmuz 2026'dan beri); depodaki README ve `ORG_README.md` hâlâ "MIT + Commons Clause" diyebilir | Tek bir doğru anlatım gerekir (karar sahibi: kurucu) |

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
| ADR statüleri | 0014, 0018–0021 uygulandı ama `proposed`; 0003 ve 0006 uygulandı ama `proposed` |
| `docs/ROADMAP.md` | Güncel (30 Eylül 2026) |
| `NOTLAR.md` (depoda) | Haziran 2026'dan kalma; SQLite, "denetim kaydı yok" gibi artık geçerli olmayan maddeler içerir. Güncel özet [Geliştirici Notları](/developer-notes/overview)'ndadır |
| Politika-digest ilk denemesi | Eski ADR-0014–0017 taslakları ve kodu (`PolicyClause`, `CompanySchema`, `PromptFlag`) birleştirilmedi; ADR numaraları yeni ADR'lerle çakıştığı için yerel bir dalda duruyor |
