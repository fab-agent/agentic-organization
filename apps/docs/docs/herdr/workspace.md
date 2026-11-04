---
sidebar_position: 2
---

# İmzalı Çalışma Alanı

> ADR-0027 · ADR-0028 · ADR-0029 · ADR-0035 · ADR-0036 · ADR-0037 · ADR-0039 (hepsi "önerildi")

## Sunucu: `GET /me/workspace`

Oturum açmış kullanıcı için `?company_id=` ile çağrılır. Kişi **istekten alınmaz**; kullanıcının o şirketteki kendi
insan `Personnel` kaydı kullanılır. Kaydı olmayan, ajan kaydı olan veya üye olmadığı şirketi isteyen kullanıcıya
404/403 döner ve hiçbir şey imzalanmaz.

| Uç nokta | Yanıt |
|---|---|
| `GET /me/workspace?company_id=` | `{manifest, bootstrap, identity}`: imzalı zarf, ilk kurulum tabanları ve çağıranın `{company_id, person_id}` kimliği (istemci ilk kullanımda sabitler) |
| `GET /me/workspace/files/{sha256}` | Dosya baytları; yalnızca çağıranın kendi profilindeki hash için |
| `GET /me/workspace/crl` | Kök tarafından imzalı, birikimli iptal listesi (yayınlandıysa) |
| `POST /me/workspace/report` | İstemcinin sayı raporu (aşağıda) |

- **Profiller** `catalog/profiles.json` ile tanımlanır; ilk eşleşen profil kazanır (`roles`, `departments`,
  `companies` anahtarları). Dosyada herhangi bir hata varsa **herkes için** 503 `profiles_invalid` döner.
- **Her manifest isteği yeni bir üretim numarası (generation) alır** ve imza çağrıdan önce hız sınırına takılır: kişi başına
  **10 saniyede bir** (`429 try_again_later`, `Retry-After: 10`). Hız sınırı nedeniyle reddedilen (429) çağrı hiçbir şey değiştirmez; sonradan başarısız olan bir çağrı (503) aralığı tüketebilir ve denetim hatası bir üretim numarası tüketir. Bu sınır yalnızca manifest üretimi içindir; dosya, CRL ve rapor uç noktaları ayrıdır.
- `gateway_url` yalnızca operatör yapılandırmasından gelir (`https` zorunlu); istek başlıklarından türetilmez.
- **Hesap başına tek insan kaydı:** aynı hesaba bağlı iki insan kaydı varsa 409 döner; davet akışı bu çifti
  oluşturamaz (yarış durumuna karşı testli). Var olan çift kayıtlar **otomatik onarılmaz** ve veritabanında
  benzersizlik anahtarı yoktur.

## İstemci: `3pa workspace`

| Komut | Ne yapar |
|---|---|
| `3pa workspace sync` | İptal listesini çeker, manifest'i doğrular, dosyaları hazırlama klasörüne indirip boyut ve SHA-256 denetler, günlüklü (geri alınabilir) bir işlemle Herdr uygulama klasörüne yazar |
| `3pa workspace status` | Kurulu paketle diskteki farkı gösterir (eksik, değişmiş, fazla) |
| `3pa workspace activate` | Yerleşim değiştiyse açık Herdr penceresinde `herdr-app do layout.switch` ile geçiş ister |
| `3pa workspace report` | Sayı raporunu sunucuya gönderir (`sync` sonrası otomatik; `--no-report` veya `THREEPA_NO_REPORT` ile kapatılır) |

Önemli bayraklar: `--root-pub` (veya `FABAGENT_WORKSPACE_ROOT_PUB`), `--app-home` (veya `HERDR_APP_HOME`),
`--company`, `--re-enroll` (farklı bir kişi/kök için yeni güven başlangıcı).

Doğrulama sırası ve garantiler:

1. **Kök anahtar sunucudan alınmaz**; kurucu veya MDM tarafından sabitlenir.
2. **İptal listesi önce** işlenir ve hemen kaydedilir.
3. Manifest'in imzası, sertifikası, süresi, kişi/şirket kimliği ve **(epoch, generation) tabanları** denetlenir;
   eski bir üretim numarası reddedilir (geri alma/replay koruması). TypeScript doğrulayıcı, Python ile ortak 60
   test vektöründe aynı kararı verir.
4. Yazma, **günlüklü bir işlemdir**: yarım kalan güncelleme bir sonraki çalıştırmada geri alınır. Aynı anda tek
   `sync` çalışır (kilit dosyası; çekirdek düzeyinde kilit değildir, sınırları ADR-0029'da yazılıdır).
5. Telemetri, ilk açılıştan **önce** kapalı yazılır.

**Yeni bir üretim numarası ne zaman gelir?** Her başarılı çağrıda. Aynı içeriğin yeniden imzalanması hata değildir.

### Sayı raporu (sapma)

`sync` sonrası istemci yalnızca **sayıları** gönderir: kurulu `epoch`/`generation`, eksik, değişmiş, fazla ve
yönetilmeyen dosya sayısı, yarım kalmış güncelleme var mı. Dosya adı, yol veya içerik gitmez. Rapor bir
**iddiadır, kanıt değildir**: sunucu bunu hiçbir erişim, politika veya imza kararında kullanmaz; ele geçirilmiş bir
istemci istediğini gönderebilir. Aynı kişiden 30 saniyede bir rapor kabul edilir.

### Yerleşimi etkinleştirme

Yerleşim kimliği değiştiyse `sync` bir etkinleştirme isteği bırakır; başlatıcı `activate --wait 60 --quiet` ile
arka planda Herdr'in kendi komutunu çalıştırır. Herdr'in `shared.json` dosyasına **hiç yazılmaz**. İstek normalde tek
seferliktir (sistem saati beş dakikadan fazla ileri sıçrarsa, çalışan bir işçi varken aynı geçiş yinelenebilir;
bkz. ADR-0036); kullanıcı sonradan bilerek başka yerleşime geçerse buna karışılmaz. Pencere yoksa komut `no_window`
bildirir (çıkış kodu mutlaka hata olmaz), istek korunur ve 7 gün sonra geçersiz olur. **Bu davranış kaynak koddan okunarak yazıldı, çalışan pencerede doğrulanmadı.**

## Anahtar yönetimi

Kök anahtar çevrimdışıdır; sunucuda imza anahtarı + sertifika bulunur. Anahtar değişimi, kayıp ve çalınma
durumları için [`docs/runbooks/workspace-signing-key-recovery.md`](https://github.com/fab-agent/agentic-organization/blob/main/docs/runbooks/workspace-signing-key-recovery.md)
adım adım yazılıdır. Önemli: kökü değiştirmek yeni bir güven başlangıcıdır (istemciler yeniden sabitlenir);
**CRL numarası veya sunucu epoch'u 2^53-1'e ulaşırsa desteklenen bir kurtarma yoktur** (ayrı bir ADR ve kod gerekir).
