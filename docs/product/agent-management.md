# Agent Management

Agent Management, organizasyon içindeki agent'ların tanımlanması, yönetilmesi ve personele atanması süreçlerini kapsar.

## Agent Nedir?

Agent, belirli bir model, skill seti ve policy ile donatılmış otonom bir varlıktır. Her agent, bir personele atanır ve o personelin iş yükünü azaltmak amacıyla kullanılır.

## Agent Özellikleri

| Özellik          | Açıklama                                      |
|------------------|-----------------------------------------------|
| Model            | Kullanılacak LLM (Claude, GPT, Gemini vb.)    |
| Skill Set        | Agent'ın kullanabileceği araçlar             |
| Policy Set       | Agent'ın uyması gereken guardrail'ler         |
| Personnel        | Agent'ın bağlı olduğu çalışan                 |
| Status           | active / draft / archived                     |

## Agent Oluşturma Akışı

1. Admin, Agent Management ekranına gider.
2. "Yeni Agent" butonuna tıklar.
3. Agent adı, model ve açıklama girilir.
4. İlgili personel seçilir.
5. Skill'ler ve Policy'ler atanır.
6. Agent oluşturulur ve personele teslim edilir.

## Agent'ın Personel ile İlişkisi

- Bir agent **sadece bir personele** atanabilir (MVP).
- Personel, kendisine atanan agent'ları Personnel Portal üzerinden kullanır.
- Agent'ın geliştirdiği skill'ler, personelin onayıyla yayınlanır.

## Agent Durumları

| Durum     | Anlamı                                      |
|-----------|---------------------------------------------|
| Draft     | Henüz tamamlanmamış, test aşamasında        |
| Active    | Kullanıma hazır, personel tarafından aktif kullanılır |
| Archived  | Kullanımdan kaldırılmış, sadece görüntülenir |

---

*Bu modül, Admin Panel'in temel bileşenlerinden biridir.*