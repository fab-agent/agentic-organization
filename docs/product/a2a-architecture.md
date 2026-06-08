---
sidebar_position: 5
---

# A2A (Agent-to-Agent) İşbirliği Mimarisi

Bu belge, 3PA'da farklı departmanlardaki agent'ların birbirinden görev talep edebildiği A2A protokolünün tasarımını açıklamaktadır.

---

## Neden A2A?

Bir organizasyonda agent'lar tek başına çalışmak yerine birbirinin yeteneklerinden yararlanabilir. Örneğin:

- Satış agent'ı, müşteri analizini Analiz departmanının agent'ından isteyebilir.
- İnsan Kaynakları agent'ı, işe alım sürecinde Hukuk agent'ından bir sözleşme taslağı talep edebilir.
- Finans agent'ı, rapor oluşturmak için Veri agent'ının hesaplama araçlarını kullanmak isteyebilir.

Bu talepler iki departmanı ve iki sorumlu insanı kapsar. A2A protokolü bu çapraz geçişi **denetlenebilir ve onay tabanlı** bir şekilde yönetir.

:::note İki aşamalı onay gerekliliği
Tek onay yeterli değildir çünkü hem görevin verilmesi (hangi agent çalışacak, ne yapacak) hem de sonucun kullanılması (ajan ne döndürdü, bu bilgiyi talep eden taraf kullanabilir mi) ayrı ayrı yönetimsel kararlar gerektirir. İki aşamalı onay bu iki kararı açık hale getirir.
:::

---

## Akış Diyagramı

```
Talep Eden Agent (A)
        │
        │  "Bu görevi senin yapmanı istiyorum"
        ▼
  A2ARequest oluştur
  status: pending_approval
        │
        │  (Bildirim: Agent B'nin sorumlusu)
        ▼
  Sorumlu İnsan (B Departmanı)
        │
    ┌───┴───────────────┐
    │ Reddet            │ Onayla
    ▼                   ▼
  status:          status: approved
  rejected              │
                        │
                        ▼
                  Agent B çalışır
                  status: running
                        │
                        ▼
                  Görev tamamlandı
                  status: pending_result_approval
                        │
                  (Bildirim: Agent A'nın sorumlusu)
                        │
                    ┌───┴───────────────┐
                    │ Reddet            │ Onayla
                    ▼                   ▼
              status:            status: completed
              rejected           Sonuç Agent A'ya döner
```

---

## İki Aşamalı Onay

| Aşama | Tetikleyici | Onaylayan | Açıklama |
|---|---|---|---|
| **Görev onayı** | A2ARequest oluşturulduğunda | Agent B'nin `responsible_id` sorumlusu | "Bu görev B'ye verilsin mi?" |
| **Sonuç onayı** | Agent B görevi tamamladığında | Agent A'nın `responsible_id` sorumlusu | "Bu sonuç A'ya iletilsin mi?" |

Bu iki kontrol noktası departmanlar arası veri akışını tam olarak denetim altında tutar. Özellikle hassas departmanlar (Hukuk, Finans) kendi agent çıktılarının başka departmanlara aktarılmasını ikinci onayda filtreleyebilir.

---

## Veri Modeli

```
A2ARequest
  ├── id                     UUID, primary key
  ├── from_session_id        FK → AgentSession (talep eden oturum)
  ├── from_agent_id          FK → AgentConfig (talep eden agent)
  ├── to_agent_id            FK → AgentConfig (hedef agent)
  ├── task                   string — görev açıklaması (serbest metin)
  ├── status                 string — durum (aşağıya bakın)
  ├── result                 string (nullable) — Agent B'nin yanıtı
  ├── approver_id            FK → Personnel (onay/red yapan insan)
  ├── created_at             datetime
  └── updated_at             datetime
```

### Durum Yaşam Döngüsü

```
pending_approval
      │
      ├── [Reddedildi] → rejected  (son durum)
      │
      └── [Onaylandı] → approved
                │
                └── [Agent B çalışmaya başladı] → running
                          │
                          └── [Tamamlandı] → pending_result_approval
                                    │
                                    ├── [Reddedildi] → rejected  (son durum)
                                    │
                                    └── [Onaylandı] → completed  (son durum)
```

| Durum | Anlamı |
|---|---|
| `pending_approval` | Görev onay bekliyor (Agent B sorumlusu) |
| `approved` | Görev onaylandı, Agent B çalışmaya başlayacak |
| `running` | Agent B aktif olarak görevi yürütüyor |
| `pending_result_approval` | Sonuç hazır, Agent A sorumlusunun onayı bekleniyor |
| `completed` | Tüm onaylar alındı, sonuç Agent A'ya iletildi |
| `rejected` | Görev veya sonuç herhangi bir onay aşamasında reddedildi |

---

## Bildirim Akışı

Uygulamada bildirimler şu kanallar üzerinden iletilebilir (gelecek fazlar):

- **Platform içi** — Sorumlu personelin panelinde bekleyen onay listesi
- **E-posta** — Atanmış e-posta adresine bildirim (AppConfig üzerinden yapılandırılır)
- **Webhook** — Harici sistemlere POST (Slack, Teams, vb.)

---

## Örnek Senaryo

```
Senaryo: Satış Agent'ı (Ali) → Analiz Agent'ı (Bülent)

1. Ali'nin agent'ı bir konuşma sırasında şunu belirler:
   "Q2 müşteri kaybı analizini Analiz departmanından isteyeyim."

2. A2ARequest oluşturulur:
   from_agent_id: ali_agent_id
   to_agent_id:   bulent_agent_id
   task:          "Q2 2026 churn analizi — segment bazlı kayıp oranları"
   status:        "pending_approval"

3. Bülent'in sorumlusu (Çiğdem) bildirim alır.
   Çiğdem görevi uygun bulur ve onaylar.
   status → "approved" → "running"

4. Bülent'in agent'ı görevi çalıştırır ve sonucu kaydeder.
   status → "pending_result_approval"

5. Ali'nin sorumlusu (Mehmet) sonucu inceler.
   Sonuç uygun, onaylar.
   status → "completed"

6. Ali'nin agent'ı sonucu alır ve konuşmaya devam eder.
```

---

## Tasarım Notları

:::tip Agent'lar arası güven
İki agent birbirini doğrudan çağıramaz; her çağrı bir insan onay noktasından geçer. Bu, otonom bir A2A zincirinin kontrolsüz büyümesini önler.
:::

:::note `from_session_id` ilişkisi
Talep, belirli bir sohbet oturumuna bağlıdır. Bu sayede A2A sonucu doğru sohbet bağlamına enjekte edilebilir ve sohbet geçmişi takip edilebilir.
:::

---

## İlgili Belgeler

- [Agent Runtime Mimarisi](../architecture/runtime.md)
- [Agent Management](./agent-management.md)
- [Personnel Portal](./personnel-portal.md)
