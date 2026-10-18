---
sidebar_position: 6
---

# Yönetici Rehberi: Anahtarlar ve Doğrulama

Aşağıdaki özellikler **şirket başına kapalı** gelir; kurucu açar. Açmadan önce ön koşulun karşılandığından emin olun.

| Ne | Nasıl | Ön koşul |
|---|---|---|
| İş incelemesi | `PUT /work-review/settings {"enabled": true, "acknowledge_notice": true}` | Çalışanlar bilgilendirildi |
| Puanlama | `PUT /work-review/settings {"rating_enabled": true, "acknowledge_notice": true}` | İş incelemesi açık, `TYPESAFE_API_KEY`, kalibre rubrik |
| Yöneticiyle paylaşım | `PUT /work-review/training-need/settings {"sharing_enabled": true}` | Hukuki inceleme |
| Niyet sınıflandırma | AppConfig `intent.enabled` + `TYPESAFE_API_KEY` | İstek metni şirket dışına çıkar |
| Çalışma alanı çalışma zamanı | `WORKSPACE_RUNTIME=fake` yalnızca test | Gerçeği yazılmadı |

## Açmadan önce karar verilmesi gerekenler

- **Hukuki inceleme (KVKK / GDPR):** puanlama ve paylaşım açılmadan önce şarttır.
- **Saklama süresi ve dışa aktarma yetkisi** (varsayılan 365 gün).
- **Asgari grup büyüklüğü** (varsayılan 3) kalıcı olsun mu.
- Anahtarlar yalnızca ortam değişkeni olarak verilir; dosyaya veya commit'e yazılmaz.

## Doğrulama

```bash
# Backend (~6 dk, arka planda çalıştırın)
cd backend && ruff check . && ruff format --check . && python -m pytest -q

# fab
cd packages/tui && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test

# fab uçtan uca (2 dk'dan uzun, pyte gerekir)
cargo build && python tests/e2e_sync.py
```

29 Eylül 2026'da PR #21 birleştiğinde: backend 931 test geçti (3 atlandı), `fab` 104 birim testi, CI'daki 10 kontrolün tamamı yeşil.

## Doğrulanmayanlar

- Canlı Jev API'si: puanlama ve kalibrasyon yalnızca sahte taşıma katmanıyla denendi.
- Tüm eşikler öneridir, ölçülmemiştir.
- Süzme yalnızca biçime bakar (isim ve düz yazı ayrıntılarını tanımaz).
- Çalışma alanı imajı Docker'da çalıştırılmadı.
- `fab` yalnızca 24×110'luk sahte terminalde denendi.

## Geliştirici notları

- Yeni migration tablo eklerse `backend/tests/test_pg_smoke.py` içindeki `added_since` listesine ekleyin; mevcut tabloya sütun eklenirse orada düşürülmeli. Aksi halde PostgreSQL CI kontrolü "relation already exists" ile kırılır.
- Sıfırdan SQLite'ta tüm Alembic zinciri çalışmaz (eski bir migration yüzünden); denemek için `create_all` + `alembic stamp <önceki revizyon>` + `upgrade head`.
- Migration head: `f8c4e1b73a26`.
