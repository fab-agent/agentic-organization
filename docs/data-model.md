# 3rdParty Agent — Data Model

**Son Güncelleme:** 29 Mayıs 2026

---

## 1. Genel Bakış

Bu doküman, sistemde kullanılacak temel modelleri ve aralarındaki ilişkileri tanımlar. Modelleme Pydantic + SQLAlchemy kullanılarak yapılacaktır.

---

## 2. Ana Modeller

### 2.1 Organization

Mevcut yapı korunur.

### 2.2 Personnel

Mevcut yapı korunur. Her personel ileride kendi agent’ına sahip olacaktır.

### 2.3 Agent (Yeni)

| Alan              | Tip          | Açıklama                              | Zorunlu |
|-------------------|--------------|---------------------------------------|---------|
| id                | UUID         | Benzersiz kimlik                      | Evet    |
| name              | String       | Agent adı                             | Evet    |
| model             | String       | Kullanılacak LLM modeli               | Evet    |
| description       | Text         | Agent açıklaması                      | Hayır   |
| status            | Enum         | active / draft / archived             | Evet    |
| personnel_id      | UUID         | Agent’ın bağlı olduğu personel        | Evet    |
| created_at        | DateTime     | Oluşturulma tarihi                    | Evet    |
| updated_at        | DateTime     | Son güncelleme tarihi                 | Evet    |

**İlişkiler:**
- 1 Agent → 1 Personnel
- 1 Agent → N Skill (AgentSkill tablosu üzerinden)
- 1 Agent → N Policy (AgentPolicy tablosu üzerinden)

### 2.4 Skill (Yeni)

| Alan              | Tip          | Açıklama                              | Zorunlu |
|-------------------|--------------|---------------------------------------|---------|
| id                | UUID         | Benzersiz kimlik                      | Evet    |
| name              | String       | Skill adı                             | Evet    |
| description       | Text         | Skill açıklaması                      | Hayır   |
| type              | Enum         | function / mcp / custom               | Evet    |
| reference         | String       | MCP adı veya fonksiyon referansı      | Hayır   |
| status            | Enum         | active / draft                        | Evet    |
| created_at        | DateTime     | Oluşturulma tarihi                    | Evet    |

**İlişkiler:**
- N Skill → N Agent (AgentSkill tablosu üzerinden)

### 2.5 Policy (Yeni)

| Alan              | Tip          | Açıklama                              | Zorunlu |
|-------------------|--------------|---------------------------------------|---------|
| id                | UUID         | Benzersiz kimlik                      | Evet    |
| name              | String       | Policy adı                            | Evet    |
| department        | String       | İlgili departman                      | Evet    |
| rules             | JSON         | Guardrail kuralları                   | Evet    |
| guardrail_type    | Enum         | content / behavior / access           | Evet    |
| created_at        | DateTime     | Oluşturulma tarihi                    | Evet    |

**İlişkiler:**
- N Policy → N Agent (AgentPolicy tablosu üzerinden)

### 2.6 AgentSkill (İlişki Tablosu)

| Alan       | Tip    |
|------------|--------|
| agent_id   | UUID   |
| skill_id   | UUID   |

### 2.7 AgentPolicy (İlişki Tablosu)

| Alan       | Tip    |
|------------|--------|
| agent_id   | UUID   |
| policy_id  | UUID   |

---

## 3. İlişki Diyagramı (Özet)

```
Organization
    │
    └── Personnel (1-N)
            │
            └── Agent (1-1)
                    │
                    ├── AgentSkill (N-N) → Skill
                    └── AgentPolicy (N-N) → Policy
```

---

## 4. Notlar

- `Personnel` ile `Agent` arasında **1-1** ilişki varsayılmaktadır (MVP için).
- Policy’ler **departman bazlı** tanımlanacaktır.
- Skill’ler **MCP** veya **custom function** türünde olabilir.
- İleride çoklu agent ve çoklu personel ilişkisi eklenebilir.

---

*Bu model, MVP için temel yapıyı oluşturur.*