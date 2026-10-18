---
sidebar_position: 12
---

# Ayarlar

**Ayarlar** (Yönetici ve üstü) altı sekmeden oluşur: AI Sağlayıcıları, Git Entegrasyonu, Yedekleme, Veritabanları, Entegrasyonlar ve Audit Log.

## AI Sağlayıcıları

Ajanların kullanacağı modellerin bağlandığı yerdir. Anahtarlar **şifrelenerek** saklanır ve ekranda bir daha düz metin olarak gösterilmez.

**Bulut API servisleri:** Anthropic, OpenAI, Google (Gemini), Mistral, Qwen (Alibaba DashScope). Anahtarı girip **Kaydet & Test Et**'e basın; durum *Aktif*, *Geçersiz key* veya *Yapılandırılmamış* olarak görünür.

**Yerel modeller:** Ollama ve LM Studio. Sunucu adresini (Base URL) girin; servis çalışıyorsa bağlantı otomatik test edilir.

**OpenAI uyumlu özel adresler:** vLLM, LiteLLM, kurum içi gateway veya OpenAI uyumlu her API. Ad, Base URL (`…/v1`), isteğe bağlı token ve (sunucu `/models` desteklemiyorsa) virgülle ayrılmış model listesi girilir.

Bir sağlayıcının anahtarı eklendiğinde modelleri ajan oluştururken seçilebilir olur.

## Git entegrasyonu

Ajan yapılandırmalarını ve departmanları bir Git deposunda YAML dosyası olarak sürümlemenizi sağlar. Aynı bağlantı [değişiklik taleplerinin](/guide/change-requests) commit'i için kullanılır.

**Bağlantı kurma:** sağlayıcı (GitHub, GitLab, Gitea), repo adresi (ör. `https://github.com/sirket/ai-capabilities`), dal (varsayılan `main`) ve erişim token'ı (GitHub için `ghp_…`, GitLab için `glpat-…`; repo yazma izni gerekir). İsteğe bağlı: *push işlemlerinde otomatik PR aç*.

**Senkronizasyon:**

| İşlem | Ne yapar |
|---|---|
| **Pull (Repo → DB)** | Depodaki YAML dosyalarını veritabanına aktarır |
| **Push (DB → Repo)** | Veritabanını YAML'a çevirir, commit eder ve gönderir (veya PR açar) |
| **Son sync geçmişi** | Her işlemin yönü, durumu, dosya sayısı, commit'i ve mesajı |

Depo düzeni:

```yaml
# agents/<slug>/agent.yaml
id: codeguard
name: CodeGuard
title: Code Review Agent
model: claude-sonnet-4-6
status: active
department: yazilim-gelistirme
responsible: elif-yildiz
skills:
  - name: Code Review
    version: '2.1'
    description: PR inceleme ve güvenlik taraması
```

Departmanlar `departments/<slug>/department.yaml` altındadır.

:::caution GitHub dışı sağlayıcılar
Arayüz GitLab ve Gitea'yı da seçilebilir sunar ve pull/push bunları tanır; ancak **değişiklik talebi commit'i yalnızca GitHub** için çalışır. Üretimde GitHub kullanın.
:::

**Sık sorunlar:**

| Belirti | Olası neden |
|---|---|
| `401` | Token süresi dolmuş: yenisini oluşturun |
| `403` | Token'da repo yazma izni yok |
| `404` | Repo adresi yanlış |
| Commit başarısız | Dal korumalıysa botun/kullanıcının doğrudan push iznine ihtiyaç var |

## Yedekleme

Veritabanını S3 uyumlu bir depoya (AWS S3, Cloudflare R2, MinIO) yedekler. Bilgiler: uç nokta (R2/MinIO için; AWS S3'te boş), bucket, ön ek (varsayılan `backups/`), bölge, erişim anahtarı ve gizli anahtar (gizli anahtar şifrelenerek saklanır). **Yedekle** düğmesi anlık yedek alır; **Son Yedekler** listesi dosya, boyut ve tarihi gösterir.

:::caution Yalnızca SQLite
Uygulama içi yedekleme şu an yalnızca **SQLite** veritabanı dosyasını yedekler. Docker kurulumları PostgreSQL kullandığı için bu düğme orada çalışmaz. PostgreSQL'i `pg_dump` ile (veya sağlayıcınızın yedek hizmetiyle) ayrıca yedekleyin ve **`data/.secret`** dosyasını da saklayın; o olmadan şifreli kayıtlar çözülemez.
:::

## Veritabanları

Ajanlara şirketin gerçek veritabanını **okuma amaçlı** sorgulatma özelliğidir.

1. **Veritabanı Ekle**: ad, tür ve bağlantı dizesi (DSN, şifreli saklanır).
2. **Keşfet**: tablolar, kolonlar ve satır sayıları okunur.
3. **Açıklamalar**: tablo ve kolonlara anlamlı açıklamalar yazın ve **örnek sorgular** ekleyin; ajan SQL üretirken bunlardan öğrenir. Ne kadar iyi açıklarsanız yanıtlar o kadar doğru olur.
4. Bir ajana **Veritabanı** türünde yetenek atayıp bu bağlantıyı seçin.

Güvenlik: yalnızca `SELECT` (ve `WITH … SELECT`) sorgularına izin verilir; `INSERT`, `UPDATE`, `DELETE`, `DROP` gibi komutlar reddedilir. Yine de bağlantı için **salt okunur bir veritabanı kullanıcısı** tanımlamanız önerilir.

## Entegrasyonlar

**Sosyal medya.** Instagram Business (kullanıcı kimliği + erişim token'ı) ve WhatsApp Business Cloud API (telefon numarası kimliği + token + varsayılan alıcı). Bilgileri kaydettikten sonra bir ajana **Instagram gönderi** veya **WhatsApp mesaj** yeteneğini ekleyin. Gönderi/mesaj bir ajan tarafından, ayarlı hesaplarla yapılır; bu yetenekleri yalnızca güvendiğiniz ajanlara verin.

**Telegram** (yalnızca kurucu). BotFather'dan bir bot oluşturun (`/newbot`), token'ı ve bildirimlerin gideceği sohbet kimliğini (`@userinfobot` ile öğrenilir) girin. Telegram şunları sağlar:

- **Bildirimler:** davet ve geçici şifreler, akış sonuçları, denetim uyarıları.
- **Etkileşimli bot:** `/ajanlar` ile ajan seçip metin yazarak sohbet, `/durum`, `/onaylar` ile bekleyen görev ve delegasyonları onaylama/reddetme.

Bot, webhook gerektirmez (sunucu Telegram'ı düzenli sorgular).

## Audit Log

Önemli işlemlerin kaydı (kim, ne zaman, hangi kayıt, ne yaptı). → [Panel → Denetim kaydı](/guide/dashboard#denetim-kaydı)
