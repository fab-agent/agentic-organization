---
sidebar_position: 3
---

# Policy ve Guardrail Yaklaşımımız

Agent'ların güvenli ve kontrollü çalışması için **Policy** (Guardrail) sistemi kritik öneme sahiptir.

## Policy Türleri

Sistemimizde üç temel policy türü tanımlıyoruz:

### 1. Content Policy
İçerik kısıtlamalarını tanımlar. Örneğin:
- Hassas veri paylaşımını engelleme
- Kişisel bilgi sızdırmama
- Yasaklı kelime ve konular

### 2. Behavior Policy
Davranış kurallarını belirler. Örneğin:
- Her zaman nazik ve profesyonel cevap verme
- Belirsiz durumlarda "bilmiyorum" deme
- Müşteriyle empati kurma

### 3. Access Policy
Erişim kısıtlamalarını tanımlar. Örneğin:
- Sadece belirli departman verilerine erişim
- Belirli MCP araçlarını kullanma yetkisi
- Zaman bazlı erişim kısıtlamaları

## Policy ve Agent İlişkisi

Her agent'a birden fazla policy atanabilir. Policy'ler, agent'ın skill kullanımını da kısıtlayabilir.

Örnek:  
*"Finance departmanındaki agent'lar, sadece finance MCP araçlarını kullanabilir."*

Bu yaklaşım, hem güvenliği artırır hem de agent'ların yetki alanını netleştirir.

---

*Devamı için: [MCP Araçları ve Skill Geliştirme](./mcp-ve-skill-gelistirme)*
