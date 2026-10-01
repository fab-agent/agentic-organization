---
sidebar_position: 2
---

# Kurulum

Üç yol var: yerel deneme, tek komutla üretim kurulumu ve manuel geliştirme kurulumu. İş tarafı için en kısa yol: önce yerel denemeyi çalıştırıp [İlk Adımlar](/getting-started/first-steps) sayfasını izlemek.

## 1. Yerel deneme (Docker)

```bash
git clone https://github.com/fab-agent/agentic-organization.git
cd agentic-organization
cp .env.example .env
# .env içinde JWT_SECRET değerini doldurun (openssl rand -hex 32)
docker compose up --build
```

Hazır olduğunda:

- Arayüz: `http://localhost:5173`
- API: `http://localhost:8000` (etkileşimli dokümantasyon: `/docs`)

Bu yığın üç servis çalıştırır: PostgreSQL (pgvector), backend ve arayüz.

## 2. Üretim kurulumu (tek komut)

Bir Ubuntu sunucuda, DNS kaydı hazırken:

```bash
git clone https://github.com/fab-agent/agentic-organization.git
cd agentic-organization
bash install.sh
```

`install.sh` sırayla şunları yapar:

1. Docker ve Docker Compose'u kontrol eder.
2. `.env` sihirbazını (`setup-env.sh`) çalıştırır.
3. Let's Encrypt (Certbot) ile SSL sertifikası alır.
4. Alan adınıza göre Nginx yapılandırmasını üretir.
5. `docker-compose.prod.yml` ile servisleri (veritabanı, backend, arayüz, Nginx) başlatır.
6. Sağlık kontrolü yapar.

`.env` sihirbazı yalnızca ortam değişkenlerini üretmek için de çalıştırılabilir: `bash setup-env.sh`. Alan adı, şirket bilgisi ve isteğe bağlı sağlayıcı anahtarlarını sorar; `JWT_SECRET` değerini kendisi üretir.

## 3. Manuel kurulum (geliştirme)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Arayüz (ayrı terminal)
cd frontend
npm install
cp .env.example .env     # VITE_API_URL=http://localhost:8000
npm run dev
```

`DATABASE_URL` verilmezse SQLite (`data/app.db`) kullanılır.

## Ortam değişkenleri

| Değişken | Gerekli mi? | Açıklama |
|---|---|---|
| `JWT_SECRET` | Evet | Oturum imzalama anahtarı, en az 32 karakter. Üretimde zayıf değer reddedilir. |
| `DATABASE_URL` | Docker'da otomatik | Varsayılan SQLite; compose dosyaları PostgreSQL'e ayarlar |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Docker'da | Veritabanı bilgileri |
| `APP_URL` | Önerilir | Davet bağlantılarında kullanılan adres |
| `CORS_ORIGINS` | İsteğe bağlı | Virgülle ayrılmış izinli adresler; varsayılan `APP_URL` |
| `RESEND_API_KEY`, `EMAIL_FROM` | İsteğe bağlı | E-posta gönderimi (Resend). Tanımlı değilse e-postalar yalnızca günlüğe yazılır. |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `MISTRAL_API_KEY`, `QWEN_API_KEY` | İsteğe bağlı | İlk açılışta bir kez içe aktarılır; Ayarlar'dan da eklenebilir |
| `SCHEDULER_ENABLED` | İsteğe bağlı | Zamanlanmış akışları çalıştıran görev zamanlayıcı (varsayılan açık) |
| `PUBLIC_BASE_URL` | İsteğe bağlı | Geliştirici iş istasyonu katmanının herkese açık API adresi |

`.env.example` ve `setup-env.sh` bir `ENCRYPTION_KEY` değişkeni de üretir, ancak kod bu değeri **okumaz**. Şifreleme anahtarı otomatik oluşturulan `data/.secret` dosyasındadır; bu dosya yedeğe dahil edilmelidir.

Telegram, Git, sosyal medya, yedekleme ve veritabanı bağlantıları ortam değişkeniyle değil, **Ayarlar** sayfasından şirket bazında yapılır.

## SSL sertifikasını elle almak

`install.sh` bunu otomatik yapar. Elle yapmak isterseniz:

```bash
docker run --rm -v /etc/letsencrypt:/etc/letsencrypt -v /var/www/certbot:/var/www/certbot \
  -p 80:80 certbot/certbot certonly --standalone \
  --email admin@sirketim.com --agree-tos -d agents.sirketim.com

sed 's/__DOMAIN__/agents.sirketim.com/g' nginx.prod.conf.template > nginx.conf
docker compose -f docker-compose.prod.yml up -d
```

Sertifika yenilemesi için haftalık bir cron görevi ekleyin: `certbot renew --quiet && docker exec <nginx-konteyneri> nginx -s reload`.

## İlk açılış

Veritabanında hiç kullanıcı yoksa uygulama sizi **kurulum sayfasına** yönlendirir. Ad soyad, şirket adı, e-posta ve şifre (en az 8 karakter) girersiniz; hesap **kurucu** rolüyle oluşturulur ve otomatik giriş yapılır. Bu sayfa yalnızca veritabanı boşken çalışır. Sabit bir yönetici şifresi yoktur.

Sonraki adım: [İlk Adımlar](/getting-started/first-steps).
