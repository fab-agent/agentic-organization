---
sidebar_position: 0
---

# Changelog

Platform güncellemelerinin kronolojik kaydı.

---

## v0.5 — 9 Temmuz 2026

### Güvenlik

#### Şirket Düzeyi Yetkilendirme
- Tüm API uç noktaları (`companies`, `departments`, `personnel`, `org-tree`, `sessions`) artık JWT sahibinin ilgili şirkete üyeliğini doğrular.
- Bir kullanıcı birden fazla şirkette üye olabilir; liste endpoint'leri yalnızca erişimi olan şirketlerin verilerini döner.
- `check_company_membership()` ve `_get_person_and_check_membership()` yardımcı fonksiyonları eklendi.

#### Pydantic Doğrulaması
- Auth endpoint'leri (`login`, `setup`, `change-password`, `invite`) artık `body: dict` yerine güçlü tipli Pydantic şemaları kullanır.
- E-posta normalizasyonu ve minimum şifre uzunluğu (8 karakter) doğrulaması schema seviyesinde uygulanır.

#### SSE Oturum Temizliği
- Sunucu-taraflı olaylar (SSE) kesildiğinde oturum durumu `active`'den `idle`'a geçer; artık askıda kalmaz.

#### Şifre Değiştirme Zorunluluğu
- Davet edilen kullanıcılar ilk girişte `/set-password` sayfasına yönlendirilir; bu sayfa atlanamaz.

### Altyapı

#### Veritabanı Migrasyonları (Alembic)
- Alembic entegrasyonu tamamlandı; artık `alembic revision --autogenerate` ile şema değişiklikleri izlenebilir.
- SQLite `ALTER TABLE` desteği için `render_as_batch=True` aktif.

#### Yapılandırılmış JSON Loglama
- `logs/app.log` dosyasına JSON formatında günlük; 30 günlük otomatik rotasyon.
- HTTP istek/yanıt logging middleware eklendi (method, path, status, ms).

#### Nginx Hız Sınırlama
- Üretim ortamı için `docker-compose.prod.yml` + `nginx.conf`: login endpoint'i IP başına dakikada 5 istek, genel API 60 istek.

#### Cloudflare Tunnel
- HTTPS kurulumu için Cloudflare Tunnel rehberi README'ye eklendi (Option C).

### Özellikler

#### S3/R2/MinIO Yedekleme
- **Ayarlar → Yedekleme** sekmesi: S3, Cloudflare R2 veya MinIO uyumlu depolama yapılandırması.
- `sqlite3.backup()` API ile güvenli çevrimiçi yedek alma, boto3 ile yükleme.
- Yedekleme geçmişi (son 20 yedek), anlık yedek alma butonu, kimlik bilgileri şifreli saklanır.

#### Sosyal Medya Ajan Skill'leri
- `instagram_post` builtin skill: Instagram Business hesabına Graph API v21.0 üzerinden fotoğraf paylaşımı.
- `whatsapp_send` builtin skill: WhatsApp Business Cloud API üzerinden metin mesajı gönderimi.
- **Ayarlar → Sosyal Medya** sekmesi: IG User ID + Access Token, WA Phone Number ID + Access Token yapılandırması; kimlik bilgileri AES-256 ile şifreli saklanır.
- Ajan yapılandırmasında bu skill'leri builtin olarak ekleyerek herhangi bir ajan sosyal medya paylaşımı yapabilir.

---

## v0.4 — 2 Temmuz 2026

### Yeni Özellikler

#### Alibaba Qwen Entegrasyonu
- **Ayarlar → AI Sağlayıcılar** sayfasına Alibaba Qwen (DashScope) eklendi.
- Desteklenen modeller: `qwen-max`, `qwen-plus`, `qwen-turbo`, `qwen-long`
- DashScope'un OpenAI uyumlu API'si üzerinden çalışır; ajan çalışma zamanında tam araç (tool-use) desteği mevcuttur.

#### İlk Kurulum Sihirbazı
- Sistemi yeni kurarken sabit bir yönetici şifresi yerine **kurulum formu** gösterilir (n8n tarzı).
- Form alanları: Ad Soyad, Şirket Adı, E-posta, Şifre, Şifre Tekrar.
- Form gönderildiğinde ilk kullanıcı `founder` rolüyle oluşturulur ve sisteme otomatik giriş yapılır.
- DB'de kullanıcı mevcut olduğunda `/setup` sayfası devre dışı kalır (403).

### Geliştirmeler
- Frontend dil seçenekleri Türkçe ve İngilizce ile sınırlandırıldı (Deutsch ve Español kaldırıldı).

---

## v0.3 — 23 Haziran 2026

### Yeni Özellikler

#### Denetim Günlüğü (Audit Log) — Tam Kapsam
- Tüm mutasyon yapan API uç noktaları (`companies`, `departments`, `personnel`, `providers`, `flows`, `change_requests`, `git_sync`) için `log_action()` çağrıları eklendi.
- Her oluşturma, güncelleme ve silme işlemi kullanıcı kimliği, şirket kimliği ve işlem detaylarıyla birlikte kaydedilir.
- Denetim günlüğü sayfası: **Ayarlar → Denetim Günlüğü**.

---

## v0.2 — 19 Haziran 2026

### Yeni Özellikler

#### Ajan Belleği
- Ajan oturumları arasında kalıcı bellek desteği eklendi.
- `MemoryStore` modeli: anahtar-değer çiftleri, TTL, şirket ve ajan bazlı kapsam.

#### Akış Araç Kullanımı (Flow Tool Use)
- Otonom akışlar artık araç çağrılarını (tool calls) destekler.
- Araç sonuçları akış geçmişine kaydedilir.

#### Çok Dilli Arayüz
- Tüm sayfalar `t()` çeviri fonksiyonuyla sarmalandı.
- Desteklenen diller: Türkçe, İngilizce.

---

## v0.1 — 1 Haziran 2026

### İlk Yayın (Faz 1 + Faz 2)

#### Temel Platform
- Şirket ve departman yönetimi (CRUD).
- İnsan ve ajan yönetimi.
- Organizasyon şeması görselleştirmesi.
- Kullanıcı rolleri ve davet sistemi (founder, executive, dept_head, agent_owner, user).
- JWT tabanlı kimlik doğrulama.

#### AI Altyapısı
- Provider key yönetimi: Anthropic, OpenAI, Google Gemini, Mistral.
- Ajan çalışma zamanı: araç çağrıları, beceri (skill) sistemi, oturum geçmişi.
- MCP (Model Context Protocol) araç desteği.

#### Entegrasyonlar
- GitHub / GitLab / Gitea entegrasyonu (markdown dosyası senkronizasyonu).
- Resend ile e-posta tabanlı davet sistemi.
- A2A (Agent-to-Agent) delegasyon protokolü.

#### Arayüz
- SvelteKit 5 + Svelte runes mimarisi.
- Özel shadcn/ui esinli bileşen kütüphanesi.
- Çok şirket desteği; sidebar şirket değiştirici.
- Karanlık / Aydınlık tema.
