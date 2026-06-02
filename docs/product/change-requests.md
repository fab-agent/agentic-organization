---
id: change-requests
title: Değişiklik Talepleri
sidebar_label: Değişiklik Talepleri
---

# Değişiklik Talepleri

Değişiklik Talepleri, ajan yapılandırması, skill veya politika değişikliklerini iki aşamalı onay akışına tabi tutar. Onay tamamlandığında değişiklik otomatik olarak GitHub reposuna commit edilir.

---

## Neden İki Aşamalı Onay?

Ajanlara tanınan yetenekler ve izinler organizasyonun operasyonel riskini etkiler. İki aşamalı onay akışı:

- **Departman Yöneticisi (dept_head)** teknik ve operasyonel uygunluğu değerlendirir.
- **Admin (executive+)** kurumsal politika ve güvenlik açısından son kararı verir ve değişikliği Git'e yazar.

---

## Durum Akışı

```
submitted
    ↓ dept_head onayı
dept_head_approved
    ↓ admin onayı + GitHub commit
committed
```

Herhangi bir aşamada reddedilebilir:

```
submitted      → rejected  (dept_head reddetti)
dept_head_approved → rejected  (admin reddetti)
```

| Durum | Açıklama |
|---|---|
| `submitted` | Talep gönderildi, bölüm onayı bekleniyor |
| `dept_head_approved` | Bölüm onaylandı, admin onayı bekleniyor |
| `admin_approved` | Admin onayladı, GitHub'a commit ediliyor |
| `committed` | Git'e başarıyla yazıldı; SHA bağlantısı mevcut |
| `rejected` | Reddedildi (her iki aşamada da oluşabilir) |

---

## Talep Türleri

| Tür | Açıklama |
|---|---|
| `agent_config` | Ajan modelinin, sistem prompt'unun veya temel yapılandırmasının değiştirilmesi |
| `skill` | Ajana yeni skill eklenmesi veya mevcut skill güncellenmesi |
| `policy` | Ajana uygulanan guardrail politikasının değiştirilmesi |

---

## Talep Oluşturma

Değişiklik talepleri doğrudan **Ajanlar** sayfasından oluşturulur. Ajan yapılandırmasında bir değişiklik yapıldığında "Değişiklik Talebi Oluştur" akışı tetiklenir; talep başlığı, türü ve önerilen yapılandırma otomatik doldurulur.

---

## Değişiklik Talepleri Sayfası

**Değişiklik Talepleri** (`/change-requests`) sayfasına `dept_head` veya üstü rollerle erişilebilir.

### Filtreleme

Sayfanın üstündeki filtre çubukları şu durumları gösterir:

| Filtre | Gösterilen |
|---|---|
| Tümü | Tüm talepler |
| Bekliyor | `submitted` durumundakiler |
| Bölüm Onaylandı | `dept_head_approved` durumundakiler |
| Commit Edildi | `committed` durumundakiler |
| Reddedildi | `rejected` durumundakiler |

### Talep Detayı

Her talep satırına tıkladığınızda genişletilmiş panel açılır:

- **Onay Akışı** — Bölüm ve admin onay/ret zamanları ve notları
- **Önerilen Değişiklikler** — Değişikliğin JSON farkı
- **GitHub SHA** — Commit edildiyse, tıklanabilir GitHub commit bağlantısı

### Eylem Butonları

**Bölüm Yöneticisi** (`dept_head+`) `submitted` talepleri için:

- **Bölüm Onayla** — Talebi `dept_head_approved` durumuna geçirir
- **Reddet** — Talebi `rejected` durumuna geçirir

**Admin** (`executive+`) `dept_head_approved` talepleri için:

- **Admin Onayla & Commit Et** — Talebi onaylar ve GitHub'a otomatik commit atar; durum `committed` olur
- **Reddet** — Talebi `rejected` durumuna geçirir

Her iki eylem için de isteğe bağlı **not** eklenebilir. Not, onay akışı geçmişinde görünür.

---

## GitHub Entegrasyonu ile İlişki

Admin onayı tamamlandığında sistem:

1. Şirkete bağlı GitHub reposunu PAT ile doğrular.
2. Ajan yapılandırma dosyasını günceller.
3. Değişikliği `feat: update agent config` benzeri bir mesajla commit eder.
4. Commit SHA'sını talep kaydına yazar.

GitHub entegrasyonu kurulu değilse admin onayı yine de çalışır ancak commit adımı atlanır.

GitHub entegrasyonu kurulumu için → [GitHub Entegrasyonu](./github-integration.md)

---

## API Endpoint'leri

| Endpoint | Yöntem | Açıklama | İzin |
|---|---|---|---|
| `/change-requests` | POST | Yeni talep oluştur | `agent_owner+` |
| `/change-requests?company_id=` | GET | Talep listesi (filtreli) | `dept_head+` |
| `/change-requests/{id}/dept-approve` | POST | Bölüm onayı | `dept_head+` |
| `/change-requests/{id}/dept-reject` | POST | Bölüm reddi | `dept_head+` |
| `/change-requests/{id}/admin-approve` | POST | Admin onayı + commit | `executive+` |
| `/change-requests/{id}/admin-reject` | POST | Admin reddi | `executive+` |
