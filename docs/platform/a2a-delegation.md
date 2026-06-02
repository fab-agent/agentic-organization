---
sidebar_position: 3
---

# A2A Delegasyon — Ajanlar Arası Görev Devri

**Delegasyon** (`/a2a`) sayfası, bir ajanın başka bir ajana görev devrettiği A2A (Agent-to-Agent) akışlarını izler ve yönetir. Her görev transferi iki insan onay noktasından geçer.

---

## Neden İki Onay?

Departmanlar arası görev devirlerinde iki bağımsız karar söz konusudur:

1. **Görev onayı** — "Bu görevi karşı tarafa verelim mi?"
2. **Sonuç onayı** — "Karşı tarafın ürettiği sonucu kullanalım mı?"

Bu iki kontrolü ayırmak, özellikle Hukuk veya Finans gibi hassas departmanların kendi çıktılarının nereye aktarılacağını denetlemesini sağlar.

---

## Durum Makinesi

```
pending_approval
      │
      ├── [Reddedildi]  → rejected  ✗
      │
      └── [Onaylandı]   → approved
                │
                └── [Ajan çalışmaya başladı] → running
                          │
                          └── [Tamamlandı] → pending_result_approval
                                    │
                                    ├── [Reddedildi] → rejected  ✗
                                    │
                                    └── [Onaylandı]  → completed  ✓
```

| Durum | Açıklama |
|---|---|
| `pending_approval` | Hedef ajanın sorumlusu görev onayı bekliyor |
| `approved` | Görev onaylandı, ajan çalışmaya hazır |
| `running` | Hedef ajan görevi aktif olarak yürütüyor |
| `pending_result_approval` | Sonuç hazır, kaynak ajanın sorumlusu inceleyecek |
| `completed` | İki onay da alındı, sonuç iletildi |
| `rejected` | Herhangi bir aşamada reddedildi |

---

## Delegasyon Sayfası Kullanımı

### Sekmeler

- **Bekleyenler** — `pending_approval` veya `pending_result_approval` durumundaki talepler
- **Tümü** — Tüm geçmiş dahil tüm talepler

### Talep Kartı

Her talep için şunlar gösterilir:

- Kaynak ajan → Hedef ajan oku
- Görev açıklaması (kısaltılmış; tıklayınca genişler)
- Durum rozeti (renkli)
- İşlem butonu (onay aşamasına göre değişir)
- Oluşturulma tarihi

### Bekleyen Sayacı

Kenar çubukta **Delegasyon** menü öğesinin yanında amber renkli rozet görünür. Bekleyen talep sayısı > 0 ise şirket kartında amber pulse noktası da belirir.

---

## Onaylama Adımları

### Görev Onayı (pending_approval)

Talep `pending_approval` durumundayken **"Onayla"** butonuna basıldığında:

```
POST /a2a/requests/{id}/approve
{ "approver_id": "personel_uuid" }
```

Durum `approved → running → pending_result_approval` sırasıyla güncellenir (arka planda ajan çalışır).

### Sonuç Onayı (pending_result_approval)

Ajan görevi tamamlamış, sonuç kayıtlıdır. **"Sonucu Onayla"** butonuna basıldığında:

```
POST /a2a/requests/{id}/approve-result
{ "approver_id": "personel_uuid" }
```

Durum `completed` olur.

### Reddetme

Her iki aşamada da **"Reddet"** butonu mevcuttur:

```
POST /a2a/requests/{id}/reject
{ "approver_id": "personel_uuid" }
```

Durum `rejected` (son durum) olur.

---

## Onaylayan Seçimi

Delegasyon sayfasında üstte bir açılır liste bulunur: şirketin insan personeli listelenir. Seçilen kişi onay/red işlemlerinde `approver_id` olarak kullanılır.

---

## API Endpoint'leri

| Method | Endpoint | Açıklama |
|---|---|---|
| `POST` | `/a2a/requests` | Yeni delegasyon talebi oluştur |
| `GET` | `/a2a/requests` | Talep listesi (`company_id` ile filtrelenebilir) |
| `POST` | `/a2a/requests/{id}/approve` | Görev onayı |
| `POST` | `/a2a/requests/{id}/approve-result` | Sonuç onayı |
| `POST` | `/a2a/requests/{id}/reject` | Reddet |
| `GET` | `/a2a/requests/pending-count` | Bekleyen talep sayısı (`company_id` filtreli) |

`company_id` query parametresi tüm liste ve sayım endpoint'lerinde desteklenir.

---

## Veri Modeli Özeti

```
A2ARequest
  ├── id                  UUID
  ├── from_session_id     Talep eden oturum
  ├── from_agent_id       Talep eden ajan
  ├── to_agent_id         Hedef ajan
  ├── task                Görev açıklaması (serbest metin)
  ├── status              Durum (yukarıya bakın)
  ├── result              Hedef ajanın yanıtı (nullable)
  ├── approver_id         Son onay/red yapan personel
  ├── created_at
  └── updated_at
```

---

## Örnek Senaryo

```
1. Satış ajanı (Ali) konuşma sırasında Q2 churn analizi ister.
   A2ARequest oluşturulur:
     from_agent_id: ali_agent
     to_agent_id:   bulent_agent (Analiz Dept.)
     task: "Q2 2026 churn analizi — segment bazlı kayıp oranları"
     status: pending_approval

2. Delegasyon sayfasında Bülent'in sorumlusu talebi görür,
   görev içeriğini inceler, "Onayla" der.
   status: approved → running

3. Bülent'in ajanı görevi çalıştırır, sonucu kaydeder.
   status: pending_result_approval

4. Ali'nin sorumlusu sonucu okur, uygun bulur, onaylar.
   status: completed

5. Sonuç Ali'nin konuşma bağlamına enjekte edilir.
```

---

## İlgili Belgeler

- [A2A Mimari Tasarımı](../product/a2a-architecture.md)
- [Agent Runtime](./agent-runtime.md)
- [İşler Sayfası](./chat-ui.md)
