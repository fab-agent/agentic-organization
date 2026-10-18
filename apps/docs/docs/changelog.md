---
sidebar_position: 99
---

# Sürüm Notları

Platformun değişiklikleri, yeniden eskiye doğru. Teknik ayrıntı için depodaki commit geçmişine ve `docs/adr/` kayıtlarına bakın.

## v1.4 — 18 Ekim 2026: Yetki sertleştirme, değerlendirme, monorepo

- **Değişiklik talepleri:** şirket ve rol denetimi, kapsam (bölüm yöneticisi yalnızca kendi bölümü), aynı kişinin iki aşamayı onaylayamaması, eşzamanlı onayda tek kazanan.
- **Davet ve rol atama:** hangi rolü kimin verebileceği API'de denetlenir; mevcut kurucu/yönetici üyeliği düşürülemez.
- **Değerlendirme (ADR-0023, aşama 1):** denetim olaylarından çalışma teşhisi ve `/eval` API'si. → [Değerlendirme](/workstation/eval)
- **Denetim zinciri:** iş istasyonu olaylarına sunucu `origin: client` damgası; politika kararları doğrulanmış `run` taşır.
- **Çok kiracılı yetki:** politika, yetenek, bölüm, üyelik, akış, oturum, davet ve token üretimi artık sahibi olan şirketin rolüne bağlı; sohbet oturumu sahibine ve ajanın yöneticilerine aittir; `draft` ajan kullanılamaz; başka bir şirketin hesabına davet şifresini sıfırlamaz.
- **Gateway:** zaman aşımı, bağlantı hatası, çözümlenemeyen yanıt, kesilen akış ve boş çıktı denetim olayına yazılır.
- **ADR'ler:** 0003, 0006, 0014–0023 kabul edildi; 0014 ve 0019'un bazı kararları ADR-0022 ile daraltıldı/yerine geçildi.
- **Depo:** dokümantasyon (`apps/docs`) ve açılış sayfası (`apps/landing`) artık bu depoda; sürüm numarası kodla hizalandı; lisans Commons Clause + MIT olarak `LICENSE` dosyasında.

**Sınırlar:** yargıçlar, görüntüleme sayfası ve tekrar oynatma henüz yok. → [Bilinen sınırlar](/developer-notes/known-limits)

## v1.3 — 30 Eylül 2026: Departman Çalışma Alanı (`fab`)

Her departmanın terminalden çalıştığı `fab` istemcisi ve arkasındaki sunucu tarafı.

- **`fab` istemcisi:** giriş, kenar çubuğu, yerel ajan paneli, `fab workspace`, `fab sync`.
- **Çalışma alanı API'si:** oluşturma, sürdürme, askıya alma, dosya manifesti, tek kullanımlık bağlanma bileti.
- **Kişi başına tek ajan**, token bütçeli prompt birleştirme, şirket bağlamı ve iş tanımı, Jev ile niyet sınıflandırma (yalnızca ilk tur, hataya açık, varsayılan kapalı).
- **İş incelemesi ve uygunluk puanları:** "İş incelemem", itiraz, rubrik ve denetleyicisi, örneklemeli puanlama, kalibrasyon aracı, eğitim ihtiyacı sinyali. Şirket başına **kapalı** gelir.
- 5 yeni veritabanı geçişi; saatlik/günlük zamanlanmış işler.

**Sınırlar:** gerçek çalışma alanı çalışma zamanı yok (yalnızca test için `FakeRuntime`); puanlama canlı Jev ile ölçülmedi ve hukuki incelemeden geçmedi. → [fab](/fab/overview)

## v1.2 — 9 Eylül 2026: Geliştirici İş İstasyonu

Yazılım geliştiricilerin kendi bilgisayarlarında **opencode** ile, sunucuya bağlı bir sandbox içinde çalışması. Web arayüzü değişmedi; bu katman yanında, isteğe bağlı çalışır.

- **Merkezi LLM gateway:** OpenAI uyumlu, kendi anahtarını getir; model izin listesi, hız ve token kotası, kullanım ölçümü.
- **Çalıştırılabilir politika motoru:** izin ver / sor / reddet; hata durumunda reddeder; `off`, `dry_run`, `enforce` kipleri.
- **Değiştirilemez denetim zinciri:** hash zincirli kayıt, dış doğrulama (S3 Object Lock / yerel günlük).
- **Kimlik:** kısa ömürlü persona token'ları, yenileme, iptal, OIDC ile giriş.
- **`3pa` CLI**, opencode eklentisi, imzalı yönetilen yapılandırma, sandbox ve çıkış filtresi, prompt injection savunması, LLM ile denetim önem puanlaması ve Telegram uyarıları.

→ [Geliştirici İş İstasyonu](/workstation/overview)

## v1.1.2 — 15 Temmuz 2026

- Lisans notu güncellendi. **Not:** 18 Temmuz 2026'da `LICENSE` dosyası tekrar düz **MIT**'e çevrildi; "Commons Clause" ifadesi artık geçerli değildir.

## v1.1.1 — 14 Temmuz 2026

- AI sağlayıcı ayarları iki bölüme ayrıldı: **yerel modeller** ve **bulut API servisleri**.
- Geçersiz anahtarlı sağlayıcı kartında **Sil** artık görünür; silme `.env`'den anahtarın geri eklenmesini önler.
- Panel'deki sabit Türkçe metinler çeviri sistemine alındı; Organizasyon sayfası İngilizce başlığı düzeltildi.

## v1.1 — 14 Temmuz 2026: Üretim hazırlığı

- **Tek komut kurulum** (`install.sh`) ve `.env` sihirbazı (`setup-env.sh`); üretim Docker yapılandırması ve HTTPS (Let's Encrypt) Nginx şablonu.
- **Yeni sürüm bildirimi:** Panel, GitHub'daki son sürümü kontrol eder (1 saat önbellek).
- **Ajan SLA tablosu:** her ajan için oturum, token, akış başarısı, görev tamamlama oranı.
- Sistem gereksinimleri ve üretim kurulum dokümantasyonu.

## v1.0 — 14 Temmuz 2026

- **Yerel modeller:** Ollama ve LM Studio birinci sınıf sağlayıcı oldu; sunucu adresi girilir, modeller otomatik çekilir.
- **Değişiklik talebi akışı:** ajan düzenlemeleri doğrudan kaydedilmez, onay akışına girer (`submitted → dept_head_approved → admin_approved → committed`), onay sonrası GitHub'a YAML commit'i.
- **Arşivleme:** ajan silme yerine arşivleme (`inactive`); veri korunur.
- Dahili araç listesi sunucudan dinamik gelir.
- Güvenlik: varsayılan `JWT_SECRET` ile başlangıçta kritik uyarı.

## v0.9 — 12 Temmuz 2026

- Token sayımı düzeltmeleri (tüm araç adımları biriktirilir; Qwen yedek hesabı).
- Akışlarda **görsel üretimi** (Qwen Image / Wanx / Flux); görev yönlendirmesi artık şirket yetenek kütüphanesini de dikkate alır.
- GitHub, Telegram, PostgreSQL ve zamanlanmış akışlar için entegrasyon testleri.

## v0.8 — 9 Temmuz 2026

- **AI ile Kurulum:** web araştırması + sohbet + önizleme + tek tıkla oluşturma.
- **Yetenekler** ve **Politikalar** sayfaları (Markdown editörü, değişiklik talebi akışı).
- Kenar çubuğunda yapı sayfaları **Yapı** altında toplandı.

## v0.6 — 9 Temmuz 2026

- Panel yeniden yazıldı: şirket ve kişisel telemetri, hafıza özetleri, şirket kimliği (vizyon, misyon, değerler, hedefler).
- Davet ve şifre bildirimleri için **Telegram** entegrasyonu; ajan sağlayıcı ekranı sadeleşti; kenar çubuğu daraltma.

## v0.5 — 9 Temmuz 2026

- **Güvenlik:** tüm uç noktalarda şirket üyeliği kontrolü; ilk girişte şifre değiştirme zorunlu; tipli giriş şemaları.
- **Altyapı:** Alembic geçişleri, JSON günlükleri, üretim Docker/Nginx yapılandırması (giriş için dakikada 5 istek sınırı).
- **Yedekleme** sekmesi (S3 uyumlu) ve **sosyal medya** yetenekleri (Instagram, WhatsApp).

## v0.4 — 2 Temmuz 2026

- Qwen (DashScope) sağlayıcısı; sabit yönetici şifresi yerine **ilk kurulum formu**; arayüz dilleri Türkçe ve İngilizce ile sınırlandı.

## v0.3 — 23 Haziran 2026

- **Denetim günlüğü:** oluşturma, güncelleme, silme işlemlerinin kaydı; Ayarlar → Audit Log.

## v0.2 — 19 Haziran 2026

- Oturumlar arası kalıcı hafıza; akışlarda araç çağrısı; Türkçe ve İngilizce arayüz.

## v0.1 — 1 Haziran 2026

İlk yayın.

- Şirket, departman, insan ve ajan yönetimi; organizasyon şeması; beş platform rolü ve davet sistemi; JWT ile kimlik doğrulama.
- Sağlayıcı anahtarı yönetimi (Anthropic, OpenAI, Google, Mistral); araç çağrılı ajan çalışma zamanı, yetenekler, oturum geçmişi, MCP desteği.
- GitHub / GitLab / Gitea senkronizasyonu; e-posta ile davet; ajanlar arası delegasyon (A2A).
- SvelteKit 5 arayüz, çok şirketli kullanım, açık/koyu tema.
