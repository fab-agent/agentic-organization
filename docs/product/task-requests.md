---
id: task-requests
title: Görev Talepleri
sidebar_label: Görev Talepleri
---

# Görev Talepleri

Görev Talebi, bir kullanıcının departman veya skill filtresi belirterek sistemden uygun bir ajan atamasını istemesidir. Platform uygun ajanı otomatik olarak seçer ve sorumlu kullanıcıya bildirim gönderir.

---

## Akış

```
Kullanıcı görev talebi oluşturur
    ↓
Sistem departman ve/veya skill filtresine göre uygun ajanı seçer
    ↓
Ajan'ın sorumlusu (responsible_user) Gelen Kutusu'nda bildirim alır
    ↓
Sorumlu görevi çalıştırır veya reddeder
    ↓
Sonuç talebi oluşturan kullanıcının Gelen Kutusu'na düşer
```

---

## Görev Talebi Oluşturma

**Gelen Kutusu** (`/inbox`) sayfasında **Görev Talebi** butonuna tıklayın. Açılan formda:

| Alan | Zorunlu | Açıklama |
|---|---|---|
| **Departman** | Hayır | Aramayı belirli bir departmanla sınırlandırır |
| **Skill Filtresi** | Hayır | Ajan skill'lerinde aranacak anahtar kelime (örn: `analiz`, `rapor`) |
| **Başlık** | Evet | Görev başlığı |
| **Açıklama** | Evet | Görev detayı — ajana gönderilecek prompt tabanı |

**Gönder** butonuna basıldığında sistem derhal uygun ajanı bulur ve sorumlusuna bildirim gönderir.

:::info Ajan Eşleşme Mantığı
Sistem, belirtilen departmanda ve skill filtresine uyan `active` durumundaki ajanları listeler; en uygun olanı seçer. Birden fazla ajan eşleşirse önce skill eşleşme puanı, eşit puanda ise boşta olan ajan tercih edilir.
:::

---

## Görev Durumları

| Durum | Açıklama |
|---|---|
| `pending` | Talep oluşturuldu, ajan henüz atanmadı |
| `assigned` | Uygun ajan bulundu ve sorumlusuna bildirildi |
| `running` | Görev LLM API ile çalıştırılıyor |
| `completed` | Görev başarıyla tamamlandı; sonuç Gelen Kutusu'nda |
| `rejected` | Sorumlu kullanıcı görevi reddetti |

---

## Sorumlu Kullanıcı Onayı

Görev atandığında sorumlu kullanıcının Gelen Kutusu'nda **Onayınızı Bekleyen Görevler** bölümünde bir kart görünür.

Kart üzerinde:
- Görev başlığı ve açıklaması
- İsteğe bağlı **not** alanı (çalışma veya reddetme gerekçesi)
- **Çalıştır** butonu — Görevi ajana gönderir, LLM yanıtı Gelen Kutusu'na düşer
- **Reddet** butonu — Görevi reddeder, talep sahibine bildirim gider

---

## Gelen Kutusu ile İlişki

Görev talebi sistemi Gelen Kutusu ile doğrudan entegre çalışır:

| Kaynak | Alıcı | İçerik |
|---|---|---|
| `task_request` | Sorumlu kullanıcı | Yeni görev atandı bildirimi |
| `task_result` | Talebi oluşturan kullanıcı | Görev tamamlandı + ajan çıktısı |

Gelen Kutusu ayrıntıları için → [Gelen Kutusu](./inbox.md)

---

## API Endpoint'leri

| Endpoint | Yöntem | Açıklama | İzin |
|---|---|---|---|
| `/task-requests` | POST | Yeni görev talebi oluştur | `user+` (tüm roller) |
| `/task-requests?company_id=` | GET | Talepler listesi | `user+` |
| `/task-requests/{id}/run` | POST | Görevi çalıştır | Sorumlu kullanıcı |
| `/task-requests/{id}/reject` | POST | Görevi reddet | Sorumlu kullanıcı |
