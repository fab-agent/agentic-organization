---
sidebar_position: 12
---

# Audit Log

Platform üzerinde gerçekleştirilen her önemli eylem otomatik olarak kayıt altına alınır. Audit Log, hangi kullanıcının ne zaman ne yaptığını izlemenizi sağlar.

---

## Neler Kaydedilir?

| Eylem | Açıklama |
|---|---|
| `create` | Yeni kayıt oluşturma (departman, personel, ajan, akış vb.) |
| `update` | Mevcut kaydı güncelleme |
| `delete` | Kayıt silme |
| `approve` | Değişiklik talebi veya görev onaylama |
| `reject` | Onay reddetme |
| `test` | AI sağlayıcı anahtar testi |
| `sync` | Git senkronizasyonu |

---

## Nereden Görüntülenir?

**Ayarlar → Audit Log** sekmesinden erişilir.

- **Entity türüne göre filtre**: Departman, personel, ajan yapılandırması, skill, akış, değişiklik talebi, sağlayıcı anahtarı
- **Eylem renk kodları**: Yeşil (create), kırmızı (delete), mavi (approve), turuncu (reject), gri (diğer)
- Varsayılan olarak en son 100 kayıt gösterilir

---

## API

```http
GET /audit
```

| Parametre | Tip | Açıklama |
|---|---|---|
| `company_id` | string | Şirkete göre filtrele |
| `entity_type` | string | Varlık türüne göre filtrele |
| `action` | string | Eyleme göre filtrele |
| `user_id` | string | Kullanıcıya göre filtrele |
| `limit` | int | Maksimum kayıt sayısı (varsayılan: 100) |

**Örnek yanıt:**
```json
[
  {
    "id": "uuid",
    "action": "create",
    "entity_type": "department",
    "entity_id": "uuid",
    "entity_name": "Yazılım Geliştirme",
    "company_id": "uuid",
    "user_id": "uuid",
    "details": null,
    "created_at": "2026-06-19T10:00:00"
  }
]
```

---

## Veri Modeli

`AuditLog` tablosu her kayıt için şunları saklar:

- **action** — yapılan eylem türü
- **entity_type** — etkilenen varlık kategorisi
- **entity_id / entity_name** — hangi kayıt etkilendi
- **company_id** — hangi şirket bağlamında
- **user_id** — eylemi yapan kullanıcı
- **details_json** — ek bağlam (önce/sonra değerleri)
- **created_at** — zaman damgası

Audit log kayıtları **salt okunur ve değiştirilemez**. Silme veya güncelleme endpoint'i yoktur.
