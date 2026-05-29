# 3rdParty Agent — Product Vision

**Son Güncelleme:** 29 Mayıs 2026

---

## 1. Ürün Vizyonu

**3rdParty Agent**, şirketlerin kendi yapay zeka ajanlarını yönetebildiği, personel bazlı chat arayüzleri sunabildiği, policy ve guardrail’lerle kontrol edilebildiği, MCP araçlarıyla genişletilebildiği bir **Agentic Şirket Platformu**dur.

Amaç: Şirket içindeki her personelin, kendi sorumluluk alanına özel ajanlara sahip olmasını ve bu ajanları güvenli, kontrollü ve geliştirilebilir şekilde kullanmasını sağlamaktır.

---

## 2. Ana Roller

| Rol          | Açıklama                                                                 | Yetkiler |
|--------------|--------------------------------------------------------------------------|----------|
| **Admin**    | Şirketin genel agent, skill ve policy yönetiminden sorumludur           | Agent, Skill, Policy CRUD + Personel atama + MCP onay |
| **Personel** | Kendi agent’ını chat arayüzü üzerinden kullanır                          | Agent kullanma, Skill geliştirme, Eval yapma |
| **Agent**    | Belirli bir model + skill + policy kombinasyonu ile çalışan varlıktır   | - |

---

## 3. Temel Kavramlar

| Kavram     | Açıklama |
|------------|----------|
| **Agent**  | Belirli bir model, skill seti ve policy ile çalışan yapay zeka varlığı |
| **Skill**  | Agent’ın kullanabileceği araç, fonksiyon veya MCP bağlantısı |
| **Policy** | Agent’ın davranışlarını kısıtlayan guardrail kuralları (departman bazlı) |
| **MCP**    | Model Context Protocol — agent’ların harici araçlara bağlanmasını sağlar |

---

## 4. Kullanım Akışı (Hedef)

1. Admin, organizasyon içinde **Agent** tanımlar.
2. Admin, Agent’a **Skill** ve **Policy** atar.
3. Admin, Agent’ı bir **Personel**’e teslim eder.
4. Personel, kendi chat ekranında Agent’ı kullanır.
5. Personel, Agent’ın sonuçlarını **eval** eder.
6. Personel, geliştirdiği skill’leri **yayınlar**.
7. Admin, yayınlanan skill’leri ve MCP taleplerini **onaylar**.

---

## 5. Uzun Vadeli Hedef

- Her departmanın kendi policy’leri ile yönetilen ajanları olması
- MCP araçlarının şirket içinde kontrollü şekilde paylaşılması
- Agent performansının eval + yayın döngüsüyle sürekli iyileştirilmesi
- Çoklu ajan orkestrasyonu ve görsel workflow desteği

---

*Bu vizyon, ürünün temel felsefesini ve uzun vadeli yönünü tanımlar.*