# Policy & Skills

Bu modül, agent'ların davranışlarını kontrol eden Policy'leri ve agent'ların kullanabileceği Skill'leri yönetir.

## Policy (Guardrail)

Policy'ler, agent'ların belirli kurallara uymasını sağlayan guardrail'lardır.

### Policy Türleri

| Tür              | Açıklama                                           | Örnek |
|------------------|----------------------------------------------------|-------|
| Content          | İçerik kısıtlamaları                               | Hassas veri paylaşımını engelleme |
| Behavior         | Davranış kuralları                                 | Her zaman nazik ve profesyonel cevap verme |
| Access           | Erişim kısıtlamaları                               | Sadece belirli departman verilerine erişim |

### Policy Oluşturma

Admin, Policy Management ekranından:
- Policy adı ve departman seçer
- Guardrail kurallarını JSON formatında tanımlar
- Policy türünü belirler
- Policy'yi oluşturur

Oluşturulan policy'ler agent'lara atanabilir.

## Skill

Skill'ler, agent'ların dış dünya ile etkileşime girmesini sağlayan araçlardır.

### Skill Türleri

| Tür              | Açıklama                                           |
|------------------|----------------------------------------------------|
| Function         | Kod ile tanımlanmış fonksiyonlar                   |
| MCP              | Model Context Protocol araçları                    |
| Custom           | Kullanıcı tanımlı özel araçlar                     |

### Skill Geliştirme Akışı

1. Personel, Personnel Portal üzerinden yeni skill geliştirir.
2. Skill'i test eder.
3. Admin'e yayınlama talebi gönderir.
4. Admin, MCP Araç Talepleri ekranından talebi inceler.
5. Onaylanan skill sisteme eklenir ve agent'lara atanabilir.

### Skill ve Policy İlişkisi

- Bir agent'a hem skill hem policy atanabilir.
- Policy'ler skill kullanımını da kısıtlayabilir.
- Örneğin: "Bu skill sadece şu policy'lere sahip agent'lar tarafından kullanılabilir."

---

*Policy ve Skill yönetimi, agent'ların güvenli ve kontrollü çalışmasını sağlar.*