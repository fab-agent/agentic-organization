---
sidebar_position: 2
---

# Ajan Çalışma Zamanı

Bu sayfa, web arayüzünde bir ajanla sohbet ettiğinizde arka planda ne olduğunu anlatır.

## Bir mesajın yolu

1. İstemci mesajı `POST /sessions/{id}/messages` ile gönderir. Yanıt, **SSE** (sunucudan gelen olaylar) akışıdır; WebSocket kullanılmaz çünkü akış tek yönlüdür ve standart HTTP'yle sorunsuz çalışır.
2. Sunucu mesajı kaydeder, veritabanı oturumunu **kapatır** (uzun LLM akışı sırasında bağlantı tutulmaz), akışı çalıştırır ve bittiğinde asistan mesajını kaydeder.
3. Oturum kapanınca arka planda bir **özet** üretilip ajanın hafızasına yazılır.

### SSE olayları

| Olay | Anlamı |
|---|---|
| `_meta` | Oturum ve akış bilgisi |
| `text` | Yanıt metni parçası |
| `tool_call` | Ajan bir araç çağırdı |
| `tool_result` | Araç sonucu |
| `done` | Bitti |
| `error` | Hata |

## Sistem prompt'u

Her tur için ajanın talimatı adlandırılmış, **token sayılı bölümlerden** birleştirilir: kimlik (ad, rol, departman), şirket bağlamı, kişinin işi, kurallar, yetenekler, politika adları, son **3 hafıza özeti** ve arama ile bulunan **ilgili bilgi**. Bütçe aşılırsa isteğe bağlı bölümler sabit sırayla düşer. Ayrıntı ve ölçümler: [fab → Kişinin ajanı ve prompt](/fab/agent-and-context).

## Model yönlendirme

Hangi modelin hangi adresten sunulacağı tek bir çözümleyiciyle belirlenir (sohbet, akışlar, görev talepleri ve gateway aynısını kullanır):

1. Ajanda **açık sağlayıcı** varsa o; ya da `sağlayıcı/model` biçiminde bir başvuru (`ollama/llama3.1`).
2. Bilinen model adı öneki (`claude-`, `gpt-`, `gemini`, `qwen`…).
3. Model listesinde o modeli içeren aktif yerel/özel adres.
4. Hiçbiri değilse Google.

Çözülen sağlayıcının **aktif bir anahtarı** olmalıdır; başka bir sağlayıcının anahtarına sessizce düşülmez. Anthropic ve Google kendi istemcileriyle, geri kalanlar (OpenAI, Qwen, Mistral, Ollama, LM Studio, özel adresler) OpenAI protokolüyle konuşulur.

## Araç döngüsü

Model bir araç çağırırsa sunucu aracı çalıştırır, sonucu modele geri verir ve model yanıtını tamamlayana kadar döngü sürer (sınırlı sayıda tur). Her araç çağrısı önce **politika motorundan** geçer (`allow / ask / deny`); varsayılan kipte (`dry_run`) karar yalnızca kaydedilir, `enforce` kipinde `deny` ve `ask` aracı engeller ve ajana "[Policy denied: …]" mesajı döner. Yetenek türlerine göre çalıştırma: [Yetenek Türleri](/technical/skill-types).

## Akışlar ve görev talepleri

Zamanlanmış akışlar ve görev talepleri aynı model çözümleyicisini ve sistem prompt'unu kullanır, ama sohbet döngüsünü değil kendi çalıştırıcılarını kullanır. Akışlarda araç çağırma yalnızca Anthropic protokollü modellerde vardır ([Otonom Akışlar](/guide/flows)).

## Hafıza ve arama

- **Hafıza:** kapanan oturumun özeti (en az 2 mesaj) `AgentMemory` olarak saklanır; yeni oturumda son 3 özet prompt'a girer.
- **Arama (RAG):** PostgreSQL'de pgvector ile oturum yanıtları, görev sonuçları ve hafızalar gömülür (15 dakikada bir artımlı); ilgili parçalar (en çok 4) prompt'a eklenir. Arama başarısız olsa bile oturum başlar.
