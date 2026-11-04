---
sidebar_position: 3
---

# Çalıştırılabilir Politika Motoru

> ADR-0005 · `backend/services/policy_engine.py`,
> `backend/services/command_parser.py`

Web arayüzündeki politikalar Markdown belgeleridir; ajanın talimatına yalnızca
**adları** girer ve model bunları bir rehber olarak yorumlar. Yürütme katmanı buna **araç çağrısından
önce çalışan** ikinci bir kapı ekler: politika motoru bir komutu görür, kurala
göre `allow` / `ask` / `deny` verir ve `enforce` modda çağrıyı fiilen durdurur.

---

## İki fonksiyon

| Fonksiyon | Ne yapar |
|---|---|
| `evaluate(...)` | Saf, yan etkisiz. Kural listesi + istek → verdict. **Fail-closed:** ayrıştırma/eşleştirme hatasında `deny`. |
| `decide(...)` | `evaluate()`'i sarar; kuralları DB'den kapsam çözerek toplar, rollout modunu uygular, sonucu denetime yazar. |

opencode plugin'i `tool.execute.before` hook'unda `POST /policy/decide` çağırır;
`enforce` modda `deny`/`ask` gelirse plugin **exception fırlatır** ve opencode
aracın başarısız olduğunu bildirir.

---

## Kapsam çözümü

Persona'dan yola çıkarak kurallar şu sırayla toplanır ve **en özel kazanır**:

```
şirket  →  departman(lar)  →  ajan
```

Üst departman politikaları alt departmanlara **miras** kalır
(`_department_chain` — `parent_id` zincirini yukarı yürür).

---

## Rollout modları

`PolicyConfig` tablosu, kapsam başına (`company` / `department` / `agent`) bir
mod tutar. En özel `PolicyConfig` kazanır; yoksa varsayılan `dry_run`.

| Mod | Davranış |
|---|---|
| `off` | Politika motoru atlanır |
| `dry_run` | Değerlendirilir ve **denetime yazılır**, ama çağrı engellenmez (varsayılan) |
| `enforce` | `deny`/`ask` verdict'i çağrıyı durdurur |

**İstisna:** fail-closed verdict'ler (kural ayrıştırılamadı, motor hata verdi)
`off` hariç **her modda** engeller — `dry_run` dahil.

### Sunucu tarafı politika kapısı (ADR-0026)

Arka uçtaki araç çağrıları (arka uç ajan araçları, akış araçları, MCP `org_policies`) tek bir kapıdan
(`agent_runtime.policy_gate`) geçer; `/policy/decide` uç noktası aynı `decide` + `audit_decision` çiftini doğrudan
çağırır. İkisi de **kapalı-başarısızdır**:

- Motor hatası, çözümlenemeyen mod/kapsam veya bilinmeyen persona çağrıyı engeller. `/policy/decide`, ele alınan
  çözümleme/değerlendirme hatalarını (ör. geçersiz mod) **HTTP 200** ile `effect: deny`, `enforced: true`,
  `fail_closed: true` döndürerek bildirir; karar tüketicisi bu alanlara bakmalıdır. Beklenmeyen bir istisna ise
  non-2xx (ör. 500) yanıt verir; çağıran bunu da başarısızlık saymalı, asla izin olarak yorumlamamalıdır. Çözümleme hatası bir uç noktadan dışarı kaçarsa (ör. yapılandırma okuyan
  uç noktalar) `503 policy_unavailable` olur.
- Karar **denetim zincirine yazılamazsa** çağrı **her modda, `off` dahil** engellenir. `off` yalnızca politika
  kurallarının değerlendirilmesini atlar.

Politika gövdesindeki çalıştırılabilir bloklar katıdır. Kapanmamış, ayrıştırılamayan veya kural biçimine uymayan blok
kaydetme sırasında `422 malformed_policy` ile reddedilir. Kayıtlı bir politika sonradan bozulursa: ayrıştırılamayan
blok o politikanın kapsamındaki kararları reddettirir; bir kuralın alanı bozuksa (ör. yanlış tipte `args`) kural
yalnızca ona ulaşan çağrıları etkileyebilir. Yani çağrılar **reddedilebilir**, hepsi değil. Sözleşme:
`docs/architecture/policy-block-contract.md`.

**Yükseltme notu:** mevcut bir kurulumu yükseltmeden önce `scripts/policy_inventory.py` çalıştırın; artık
ayrıştırılamayan bir politika veya yazılamayan denetim zinciri araç çağrılarını engeller.

**Hâlâ açık:** politika değişiklik istekleri doğrulanır ama Policy tablosuna uygulanmaz; arka uçtaki bazı sohbet
yolları sağlayıcı SDK'larını ortak gateway katmanı dışında çağırır.

`resolve_mode(...)` etkin modu döndürür; `3pa policy` bunu ve etkin kural
listesini gösterir.

---

## Komut eşleştirme

Bash komutları `command_parser.py` içinde [`bashlex`](https://github.com/idank/bashlex)
ile **AST'ye** ayrıştırılır. Kural `rm -rf /` yazdığında, `rm  -rf  /`,
`rm --recursive --force /`, `/bin/rm -rf /` gibi string kaçışları da yakalanır.

```
{ "match": "command", "command": "rm", "args_contain": ["-rf", "/"], "effect": "deny" }
```

Ayrıştırılamayan bir komut → fail-closed → `deny`.

---

## Taban kurallar

Motor, hiçbir şey yapılandırılmasa bile bir dizi **yıkıcı komut** taban kuralıyla
gelir (disk silme, fork bomb, kimlik bilgisi dosyalarını okuma, `curl | sh`
kalıpları). Bunlar `dry_run`'da uyarı üretir, `enforce`'da engeller.

---

## Nereye bağlı

- opencode plugin → `POST /policy/decide` (iş istasyonu)
- `agent_runtime.execute_skill()` → web arayüzündeki ajanlar için aynı motor
- `3pa policy` → persona için etkin kuralların önizlemesi
- ADR-0013 önem skorlaması → yüksek-önem birikimi `PolicyConfig`'i otomatik
  `enforce`'a çekebilir

---

## Açık konular

- Kural yazımı için frontend arayüzü (şu an kurallar JSON).
- `PolicyConfig` sıfırlama / mod değiştirme için operatör ekranı.
