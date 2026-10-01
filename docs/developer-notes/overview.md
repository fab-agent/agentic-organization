---
sidebar_position: 1
---

# Geliştirici Notları

Bu bölüm platformu geliştiren ve inceleyen kişiler içindir: neden bu teknolojileri seçtik, hangi kararları verdik, hangi fikirleri eledik, nerede duruyoruz. İş kullanıcıları bu bölümü atlayabilir. Kayıt altına alınmış resmi kararlar depodaki `docs/adr/` altındadır; burası onların özeti ve arka planıdır.

## Teknoloji seçimleri

| Alan | Seçim | Neden |
|---|---|---|
| Backend | FastAPI + SQLModel | Async, otomatik OpenAPI, Pydantic doğrulaması; tek model hem ORM hem şema |
| Veritabanı | PostgreSQL 16 + pgvector (dev: SQLite) | Başlangıçta SQLite'tı (tek dosya, basit yedek); anlamsal arama ve çok işlemli çalışma için PostgreSQL'e geçildi |
| Arayüz | SvelteKit 5 + Tailwind | Küçük paket, runes sistemi az kalıp kod gerektirir; temel bileşenler (Button, Badge, Input…) shadcn-svelte'in o dönemki Svelte 5 uyumsuzluğu yüzünden bize ait |
| Zamanlama | APScheduler (işlem içi) | Celery + Redis gibi ayrı servis gerektirmez; çok işlemde kilit dosyasıyla tek lider |
| Git | PyGithub (GitHub Contents API) | Sunucuda klon yönetmek yerine tek HTTP çağrısı; SHA yönetimi otomatik |
| Git kimlik doğrulama | Kişisel erişim token'ı (PAT) | MVP için yeterli; OAuth (callback, gizli anahtar yönetimi) ertelendi |

## Verilen mimari kararlar

- **Değişiklik talepleri iki aşamalı: bölüm yöneticisi → yönetici.** "Kurucu onaylasın" fikri ölçeklenmediği için bırakıldı. Bölüm yöneticisi teknik uygunluğa, yönetici kurumsal risk ve politikaya bakar. → [Değişiklik Talepleri](/guide/change-requests)
- **Görev yönlendirmesi üst departman zincirinde yükselir.** Önce aynı departmanda yetenek eşleşmesi aranır, bulunamazsa `parent_id` zinciri yukarı tırmanılır. Merkezi "genel ajan havuzu" yerine organik yönlendirme. → [Görev Talepleri](/guide/tasks-and-inbox)
- **Tek bir bildirim katmanı.** Akış sonuçları, görev bildirimleri ve sistem mesajları aynı `InboxMessage` tablosuna düşer; `source_type` ayırt eder. Yeni olay türü eklemek gelen kutusu kodunu değiştirmez.
- **İnsan onayı ajan zincirinin içinde.** Ajanlar arası devir iki insan onayı ister; ajanlar birbirini insansız çalıştıramaz. → [Delegasyon](/guide/delegation)
- **Geliştirici ve departman katmanı ayrı kapılar, ortak çekirdek.** Aynı gateway, politika motoru ve denetim zinciri; yüzey kişinin işine göre değişir (opencode / `fab` / web).

## Mimari karar kayıtları (ADR)

| ADR | Konu | Durum |
|---|---|---|
| 0001 | Geliştirici istemcisi olarak opencode | kabul edildi |
| 0002 | Yürütme modeli: laptop + zorunlu yerel sandbox | kabul edildi |
| 0003 | Tehdit modeli ve zorlama sınırları | önerildi |
| 0004 | Merkezi LLM gateway (OpenAI uyumlu, kendi anahtarını getir) | kabul edildi |
| 0005 | Çalıştırılabilir politika motoru (hata durumunda reddeden) | kabul edildi |
| 0006 | Değiştirilemez (hash zincirli) denetim | önerildi (uygulandı) |
| 0007 | Ajan kimliği ve kısa ömürlü kimlik bilgileri | kabul edildi |
| 0008 | TUI stratejisi | kabul edildi; TUI teknolojisi ADR-0014 ile değişti |
| 0009 | `3pa` iş istasyonu CLI'ı | kabul edildi |
| 0010 | Prompt injection savunması | kabul edildi |
| 0011 | Yönetilen yapılandırma ve öncelik | kabul edildi |
| 0012 | Depo yapısı ve sürüm süreci | kabul edildi |
| 0013 | LLM ile denetim önem puanlaması | kabul edildi |
| 0014 | Her departman için terminal çalışma alanı (`fab`) | önerildi |
| 0015 | Şirket belgelerini alma (Docling) ve sıralama (Jev) | önerildi, kod yok |
| 0016 | Kurulum kiti: organizasyon şeması, kimlik, modeller, şirket sistemleri | önerildi |
| 0017 | Politikalar kod olarak (sürümlü) ve günlük iş incelemesi | önerildi, kod yok |
| 0018 | Çalışma alanı yaşam döngüsü API'si | önerildi |
| 0019 | Kişi başına tek ajan ve iş incelemesi | önerildi |
| 0020 | Token bütçeli prompt ve niyet ayrıştırma | önerildi |
| 0021 | Uygunluk rubriği | önerildi |

0014 ve 0018–0021 büyük ölçüde uygulandı ama statüleri hâlâ `proposed`; kabul kararı bekliyor. Ayrıntı ve sıradaki işler: depodaki `docs/ROADMAP.md`.

## Planlanan: politikaları yerel bir git sistemiyle yönetmek

Bugün Git entegrasyonu GitHub'a bağlıdır (değişiklik talebi commit'i). Planlanan yön (ADR-0017): şirket politikalarının, rubriğin ve ajan yapılandırmalarının **şirketin kendi yerel git sisteminde**, bir kod kütüphanesi gibi sürümlenmesi; değişikliklerin değişiklik talebi akışından geçmesi; git'in "gerçeğin kaynağı", veritabanının ise bundan yeniden kurulabilen önbellek olması. Bu henüz yazılmadı.

## Strateji notları (Eylül 2026 tartışmasının özeti)

**Politika belgelerini işletilebilir kılma (Docling + Jev).** Büyük şirketlerin yüzlerce politika belgesini Docling ile içeri alıp, guardrail'leri bağlam penceresinin dışına taşımak ve TypeSafe AI "Jev" ile denetlemek fikri araştırıldı. Bulgular:

- Jev, **metin üretmeyen** bir sınıflandırıcıdır (tipli sorulara olasılık verir). Net ihlal/uyum vakalarını çok iyi ayırdı; **belirsiz vakalarda tutarsızdı**. Bu yüzden tek başına karar verici değil, bir "hakem" olarak kullanılır ve insan gözetimiyle birlikte.
- Docling, PDF'leri `pypdf`'ten çok daha temiz çıkarır ama başlık/alt bilgi tekrarları için bir **temizleme katmanı** gerekir.
- Bir LLM'in ürettiği özetlerde "izin sınırı"nı "yükümlülük" diye yazması gibi **anlamsal hatalar** görüldü; sadece alıntı eşleştirmesi yetmez.
- Bu sunucuda yerel model çalıştırmak mümkün değil (GPU yok); sağlayıcılar harici kalır.
- Jev'in gizlilik/saklama koşulları doğrulanmadan **gerçek şirket belgeleri** ona gönderilmemelidir.

**Araçların yerine geçmek yerine arasına girmek.** Hedef, çalışanların kullandığı araçları (opencode, benzeri geliştirici araçları, ileride sohbet uygulamaları) değiştirmek değil, aralarına girip kullanım, maliyet ve uygunluğu görünür kılmak. İki kademe:

- **Kademe A:** adresi (base URL) ayarlanabilen araçlar. Mevcut gateway'in doğal uzantısı; düşük risk. **Önce bu.**
- **Kademe B:** SaaS sohbet uygulamaları (araya girme/MITM). AI-DLP/CASB pazarına girmek demektir: aylar süren, ayrı bir mühendislik ve hukuki ağırlık. Yol haritasında kalır, küçük bir pilotla sınırlı.

**Cihaz kimliği olarak MAC adresi çalışmaz** (taklit edilebilir, katman 2'dir ve bulut sunucu göremez, işletim sistemleri varsayılan olarak rastgeleleştirir). Doğrusu cihaz sertifikası + SSO. Hiyerarşik raporlama için `CompanyMember.role/scope_id` ve politika motorunun departman zinciri zaten hazırdır.

**İnsan kullanımı sinyali ajan denetiminden ayrıdır.** Ajanlar için denetim zinciri enjeksiyon savunmasının parçasıdır; insan çalışanlar için daha hafif, **asenkron ve danışma amaçlı** bir sinyal gerekir (engellemez). Web sohbet akışında, mesaj modele gitmeden hemen önce sunucu tarafında zaten bir kanca noktası vardır; Kademe B'ye gerek kalmadan buradan başlanabilir.

**Sınıflandırma şeması sabit olmamalı ama tam otonom da olmamalı.** Taksonomi ve Jev soruları her şirketin kendi belgelerinden **üretilmeli**, fakat devreye alma **insan onaylı** olmalı (`draft` → `active`). Ölçülen hatalar (yukarıdaki) tam otonomiyi savunulamaz kılıyor. Bu, mevcut `dry_run → enforce` ve değişiklik talebi desenleriyle aynı mantık. ADR-0021'deki rubrik tasarımı (taslak → gölge → canlı) bu ilkeyi uygular.

## Geliştirme ve doğrulama

```bash
# Backend (~6 dk)
cd backend && ruff check . && ruff format --check . && python -m pytest -q

# fab (Rust)
cd packages/tui && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

Dikkat edilecekler:

- **Yeni migration tablo ekliyorsa** `backend/tests/test_pg_smoke.py` içindeki `added_since` listesine ekleyin; mevcut tabloya sütun ekliyorsa orada düşürülmeli. Aksi halde PostgreSQL CI kontrolü "relation already exists" ile kırılır.
- **Sıfırdan SQLite'ta tüm Alembic zinciri çalışmaz** (eski bir geçiş yüzünden). Denemek için `create_all` + `alembic stamp <önceki revizyon>` + `upgrade head`.
- Mimari açıdan önemli dosya değişiklikleri bir ADR ister (`adr-guard` iş akışı); gerekmiyorsa PR'a `no-adr-needed` etiketi konur.
- **Anahtarlar** yalnızca ortam değişkeni olarak verilir; dosyaya ya da commit'e yazılmaz. Bir anahtar sohbete/kayda sızdıysa döndürülmüş sayın.
