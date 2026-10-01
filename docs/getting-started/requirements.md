---
sidebar_position: 1
---

# Gereksinimler

Bu sayfa BT sorumluları içindir. Kurulumdan önce sunucunuzun aşağıdakileri karşıladığından emin olun.

## Sunucu

| | Minimum | Önerilen |
|---|---|---|
| İşlemci | 2 vCPU | 4 vCPU |
| Bellek | 4 GB | 8 GB |
| Disk | 20 GB SSD | 50 GB SSD |
| İşletim sistemi | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |

Platform bir yapay zeka modeli **çalıştırmaz**; harici sağlayıcılara (veya sizin yerel model sunucunuza) bağlanır. Bu yüzden GPU gerekmez.

## Yazılım

**Docker ile kurulum (önerilen):**

| Yazılım | Sürüm |
|---|---|
| Docker Engine | 24.0+ |
| Docker Compose | v2.20+ |
| `openssl` veya `python3` | herhangi biri (gizli anahtar üretmek için) |

**Manuel (geliştirme) kurulum:** Python 3.11+, Node.js 20+, bir PostgreSQL 16 (pgvector eklentisiyle) veya yerel deneme için SQLite.

## Veritabanı

Docker kurulumları **PostgreSQL 16 + pgvector** ile gelir (`pgvector/pgvector:pg16` imajı); ayrı bir kurulum yapmanız gerekmez. pgvector, ajan hafızası ve geçmiş oturumlarda anlamsal arama içindir.

SQLite yalnızca yerel geliştirme içindir (`DATABASE_URL` verilmezse kullanılır).

:::caution Yedekleme
Ayarlar'daki uygulama içi yedekleme şu an yalnızca SQLite dosyasını yedekler. PostgreSQL kullanıyorsanız (Docker kurulumunun varsayılanı) veritabanını `pg_dump` ile ayrıca yedekleyin. Ayrıntı: [Ayarlar → Yedekleme](/guide/settings#yedekleme).
:::

## Ağ ve alan adı

| Port | Kullanım |
|---|---|
| 80 | HTTP (sertifika doğrulaması ve HTTPS yönlendirmesi) |
| 443 | HTTPS |

Üretimde yalnızca 80, 443 ve SSH dışarıya açık olmalıdır. Geliştirme ortamında backend `8000`, arayüz `5173` portunda yalnızca `localhost`'a açılır.

Üretim için bir alan adı veya alt alan adı gerekir (ör. `agents.sirketim.com`). Kurulumdan **önce** DNS A kaydı sunucunuzun IP adresini göstermelidir; yayılması 5 dakika ile 48 saat sürebilir (`nslookup agents.sirketim.com` ile kontrol edin). `install.sh` tek bir alan adı için Let's Encrypt sertifikası alır.

Her şirkete ayrı alt alan adı (`sirket.agent.sirketim.com`) vermek istiyorsanız çok kiracılı kurulum gerekir; bkz. [Mimari → Çok kiracılı kurulum](/technical/architecture#çok-kiracılı-alt-alan-adları).

## Yapay zeka sağlayıcıları

Kurulum sırasında veya sonradan **Ayarlar → AI Sağlayıcıları** sayfasından en az bir sağlayıcı ekleyin. [AI ile Kurulum](/guide/onboarding) ve ajan sohbetleri bu anahtara ihtiyaç duyar.

| Sağlayıcı | Not |
|---|---|
| Anthropic, OpenAI, Google, Mistral, Qwen (Alibaba) | Bulut API'si; anahtar gerekir |
| Ollama, LM Studio | Kendi sunucunuzda çalışan yerel modeller; adres girilir |
| OpenAI uyumlu özel adres | vLLM, LiteLLM, kurum içi gateway gibi; adres + isteğe bağlı token |

## Güvenlik notları

- `JWT_SECRET` (oturum imzalama) en az 32 karakter olmalıdır; `setup-env.sh` bunu otomatik üretir.
- Kayıtlı sağlayıcı anahtarları, token'lar ve veritabanı bağlantı bilgileri bir **Fernet anahtarıyla** şifrelenir. Anahtar ilk çalışmada `data/.secret` dosyasına yazılır (izin `600`). Bu dosyayı kaybederseniz şifreli kayıtlar çözülemez: veritabanı yedeğiyle **birlikte** saklayın.
- `ENVIRONMENT=production` iken uygulama, yer tutucu veya kısa bir `JWT_SECRET` ile **başlamayı reddeder**.
- Veri dizinine ve veritabanı portuna dışarıdan erişim olmamalıdır.
- Nginx giriş sayfasına hız sınırı uygular.
