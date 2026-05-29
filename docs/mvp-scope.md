# 3rdParty Agent — MVP Kapsamı (Aşama 1)

**Son Güncelleme:** 29 Mayıs 2026  
**Hedef:** Admin panelinde Agent, Skill ve Policy yapılarını kurmak

---

## 1. MVP Tanımı

Bu MVP, **Admin Paneli** üzerinden aşağıdaki yapıları yönetebilmeyi hedefler:

- Agent tanımlama ve personele atama
- Skill tanımlama
- Policy (guardrail) tanımlama
- Agent ↔ Skill ↔ Policy ilişkilendirme

**Not:** Personel chat ekranı, eval, yayınlama ve MCP onay akışı bu MVP’de yer almaz.

---

## 2. Backend (FastAPI) — MVP Kapsamı

### Modeller

| Model          | Alanlar                                                                 | İlişkiler                  |
|----------------|-------------------------------------------------------------------------|----------------------------|
| `Agent`        | id, name, model, description, status, personnel_id                      | Personnel (1-1)            |
| `Skill`        | id, name, description, type, reference, status                          | Agent ile çoktan çoğa      |
| `Policy`       | id, name, department, rules (JSON), guardrail_type                      | Agent ile çoktan çoğa      |
| `AgentSkill`   | agent_id, skill_id                                                      | -                          |
| `AgentPolicy`  | agent_id, policy_id                                                     | -                          |

### Endpoint’ler

| Method | Endpoint                              | Açıklama                              | Öncelik |
|--------|---------------------------------------|---------------------------------------|---------|
| POST   | `/agents`                             | Yeni agent oluşturma + personele atama | Yüksek  |
| GET    | `/agents`                             | Tüm agent’ları listeleme              | Yüksek  |
| GET    | `/agents/{id}`                        | Agent detayı                          | Orta    |
| POST   | `/skills`                             | Yeni skill oluşturma                  | Yüksek  |
| GET    | `/skills`                             | Tüm skill’leri listeleme              | Yüksek  |
| POST   | `/policies`                           | Yeni policy oluşturma                 | Yüksek  |
| GET    | `/policies`                           | Tüm policy’leri listeleme             | Yüksek  |
| POST   | `/agents/{id}/skills`                 | Agent’a skill ekleme                  | Orta    |
| POST   | `/agents/{id}/policies`               | Agent’a policy ekleme                 | Orta    |

---

## 3. Frontend (SvelteKit) — MVP Kapsamı

### Sayfalar

| Sayfa          | Özellikler                                                        | Öncelik |
|----------------|-------------------------------------------------------------------|---------|
| `/agents`      | Agent listesi + oluşturma modal’ı + personele atama               | Yüksek  |
| `/skills`      | Skill listesi + oluşturma modal’ı                                 | Yüksek  |
| `/policies`    | Policy listesi + oluşturma modal’ı (departman seçimi)             | Yüksek  |
| Agent Detay    | Skill ve Policy ekleme/çıkarma (ileride)                          | Orta    |

### UI Bileşenleri

- Agent kartı: İsim, model, bağlı personel, skill sayısı
- Skill kartı: İsim, tür, açıklama
- Policy kartı: İsim, departman, guardrail türü
- Modal’lar: Yeni Agent, Skill, Policy oluşturma

---

## 4. MVP’de Yer Almayanlar (İkinci Aşama)

- Personel chat ekranı
- Gerçek LLM çağrısı ve tool calling
- Eval ve yayınlama döngüsü
- MCP araç talebi ve onay sistemi
- Admin onay paneli
- Çoklu ajan orkestrasyonu
- Görsel workflow / kanban

---

## 5. Başarı Kriterleri

- Admin, agent oluşturup bir personele atayabilmeli
- Admin, skill ve policy tanımlayabilmeli
- Agent’a skill ve policy bağlanabilmeli
- Tüm veriler veritabanında kalıcı olarak saklanmalı

---

*Bu doküman, ilk MVP’nin sınırlarını tanımlar.*