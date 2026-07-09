---
sidebar_position: 7
---

# Yedekleme

Veritabanını istediğiniz zaman S3, Cloudflare R2 veya MinIO gibi S3 uyumlu bir depolamaya yedekleyebilirsiniz.

---

## Yapılandırma

**Ayarlar → Yedekleme** sekmesine gidin ve aşağıdaki bilgileri doldurun:

| Alan | Açıklama |
|---|---|
| Bucket Adı | S3 bucket ismi (örn. `my-org-backups`) |
| Prefix | Yedek dosyaların alt klasörü (varsayılan: `backups/`) |
| Endpoint URL | Boş bırakırsanız AWS S3. Cloudflare R2/MinIO için doldurun |
| Access Key ID | S3/R2 erişim anahtarı |
| Secret Access Key | Gizli anahtar — AES-256 ile şifreli saklanır |
| Region | Bölge (varsayılan: `us-east-1`) |

Kaydet butonuna bastıktan sonra yapılandırma durumu kart başlığında görünür.

---

## Yedek Alma

Yapılandırma tamamlandıktan sonra **Yedekle** butonuna tıklayın.

Sistem:

1. `sqlite3.backup()` API ile veritabanının çevrimiçi, tutarlı bir kopyasını oluşturur.
2. Kopyayı `app_YYYYMMDD_HHMMSS.db` formatında adlandırır.
3. Dosyayı yapılandırılan bucket'a yükler.

Her yedek sonucu (başarı/hata, boyut, timestamp) otomatik olarak geçmişe kaydedilir (son 20 kayıt).

---

## Desteklenen Depolama Sağlayıcıları

| Sağlayıcı | Endpoint URL |
|---|---|
| AWS S3 | *(boş bırakın)* |
| Cloudflare R2 | `https://<account_id>.r2.cloudflarestorage.com` |
| MinIO | `http://minio.iç-ağ:9000` |
| Wasabi | `https://s3.wasabisys.com` |
| Backblaze B2 | `https://s3.us-west-004.backblazeb2.com` |

---

## Güvenlik

- Secret Access Key hiçbir zaman düz metin olarak saklanmaz; Fernet (AES-256-CBC) ile şifrelenir.
- Yedek dosyaları SQLite formatındadır; geri yükleme için `data/app.db` dosyasının üzerine yazmanız yeterlidir.

---

## API

| Endpoint | Açıklama |
|---|---|
| `GET /backup/config` | Mevcut yapılandırmayı döner (token redacted) |
| `PUT /backup/config` | Yapılandırmayı kaydeder/günceller |
| `DELETE /backup/config` | Tüm yapılandırmayı siler |
| `POST /backup/now` | Anlık yedek başlatır |
| `GET /backup/history` | Son 20 yedek kaydını listeler (yeniden eskiye) |
