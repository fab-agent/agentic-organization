---
id: department-hierarchy
title: Departman Hiyerarşisi
sidebar_label: Departman Hiyerarşisi
---

# Departman Hiyerarşisi

fab.engineering, şirket içi birimleri hiyerarşik biçimde modellemenize olanak tanır. Her departman bir üst departmana bağlanabilir; böylece şirket yapınız düz bir liste yerine gerçek bir ağaç haline gelir.

---

## Temel Kavramlar

| Kavram | Açıklama |
|---|---|
| **Kök Departman** | Üst birimi olmayan, hiyerarşinin en üstündeki departman |
| **Alt Birim** | Bir kök veya başka bir alt departmana bağlı olan departman |
| `parent_id` | Alt birimin üst departmanının veritabanı kimliği |

---

## Departman Oluşturma

**Departmanlar** sayfasına gidin ve **Yeni Departman** butonuna tıklayın. Sağ taraftan açılan formda şu alanları doldurun:

1. **Departman Adı** — Zorunlu. Örnek: `Yazılım Geliştirme`
2. **Slug** — URL dostu kısa ad. Türkçe karakterler otomatik dönüştürülür; elle düzenlenebilir.
3. **Üst Departman** — Hiyerarşi oluşturmak istiyorsanız buradan üst birimi seçin. Kök birim bırakmak için boş bırakın.
4. **Açıklama** — Departmanın sorumluluklarını kısaca tanımlayan serbest metin.
5. **Departman Hedefleri / OKR** — Her satır ayrı bir hedef olarak sayılır. Serbest metin.
6. **Departman Politikaları** — Bu departmana bağlı tüm ajanların uyacağı kural listesi. Her politikayı ayrı ayrı ekleyin.
7. **Durum** — `Aktif` veya `Pasif`.

**Kaydet** butonuna basıldığında departman oluşturulur ve tabloya eklenir.

:::info Slug Otomatik Üretimi
Departman adı yazıldıkça slug alanı otomatik doldurulur. Dilediğinizde elle geçersiz kılabilirsiniz. Slug, organizasyon yapısının Git repolarına yazılmasında dizin adı olarak kullanılır.
:::

---

## Hiyerarşi Kuralları

- Bir departman, aynı anda **yalnızca bir** üst departmana bağlanabilir.
- Bir departman kendi kendisini üst birim olarak seçemez.
- Döngüsel bağımlılık oluşturulmasını önlemek için form, zaten bir alt birim olan departmanları üst birim listesinden dışlar.
- Bir departman silindiğinde altındaki birimlerin `parent_id` bağlantısı kaldırılır (alt birimler kök birimlere dönüşür, silinmez).

---

## Departman Listesi

Departmanlar sayfası üç sayım kartıyla özetlenir:

| Kart | Açıklama |
|---|---|
| **Toplam** | Şirketin tüm departmanları |
| **Aktif** | `Aktif` durumundaki departmanlar |
| **Alt Birim** | `parent_id` dolu olan, yani bir başka departmana bağlı birimler |

Tabloda her departmanın **Üst Birim** sütunu, varsa bağlı olduğu birimi gösterir. Alt birim satırlarında ↳ işareti ve mor renk kullanılır; kök birimler mavi renktedir.

---

## Org Chart — Departman Görünümü

**Organizasyon** sayfasında iki farklı görünüm vardır:

| Görünüm | Açıklama |
|---|---|
| **Personel Ağacı** | Her personeli ve ajanını gösteren hiyerarşik ağaç |
| **Departman** | Departmanları hiyerarşiye göre listeleyen ve her birimin insan/ajan sayısını gösteren kompakt görünüm |

Departman görünümünde kök birimler daraltılabilir/genişletilebilir; her birimin yanında o birimde çalışan insan sayısı ve ajan sayısı gösterilir. Alt birimler girintili biçimde listelenir.

---

## Departman ve Politikalar

Bir departmana eklenen politikalar, o departmana bağlı tüm ajanların varsayılan guardrail listesini oluşturur. Ajan yapılandırması sırasında bu politikalar otomatik olarak ön seçili gelir.

Politika yönetiminin ayrıntıları için → [Policy & Skills](./policy-and-skills.md)

---

## API Endpoint'leri

| Endpoint | Yöntem | Açıklama | İzin |
|---|---|---|---|
| `/departments` | POST | Yeni departman oluştur | `dept_head+` |
| `/departments?company_id=` | GET | Şirketin tüm departmanları | `dept_head+` |
| `/departments/{id}` | PUT | Departman güncelle | `dept_head+` |
| `/departments/{id}` | DELETE | Departman sil | `dept_head+` |
| `/departments/tree?company_id=` | GET | Hiyerarşik ağaç (parent→children) | `dept_head+` |
