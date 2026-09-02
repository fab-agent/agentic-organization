import * as p from '@clack/prompts'
import chalk from 'chalk'
import { existsSync } from 'fs'
import { resolve } from 'path'
import { PROVIDERS, testProviderKey } from '../utils/providers.js'
import { writeEnv } from '../utils/env.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

function cancel(msg = 'İşlem iptal edildi.'): never {
  p.outro(chalk.yellow(msg))
  process.exit(0)
}

function checkCancel<T>(value: T): Exclude<T, symbol> {
  if (p.isCancel(value)) cancel()
  return value as Exclude<T, symbol>
}

// ── Banner ────────────────────────────────────────────────────────────────────

function printBanner() {
  console.log()
  console.log(chalk.blue('  ┌──────────────────────────────────────────┐'))
  console.log(chalk.blue('  │') + chalk.bold.white('   3rdParty Agent') + chalk.dim(' — Kurulum Sihirbazı    ') + chalk.blue('│'))
  console.log(chalk.blue('  │') + chalk.dim('   Ajanlarınızı ve politikalarınızı       ') + chalk.blue('│'))
  console.log(chalk.blue('  │') + chalk.dim('   merkezi olarak yönetin.                ') + chalk.blue('│'))
  console.log(chalk.blue('  └──────────────────────────────────────────┘'))
  console.log()
}

// ── Main ──────────────────────────────────────────────────────────────────────

export async function init() {
  printBanner()
  p.intro(chalk.bgBlue.bold.white(' KURULUM SİHİRBAZI ') + chalk.blue(' adım adım ilerleyeceğiz (~2 dk)'))

  // ─ Already initialized? ──────────────────────────────────────────────────
  const envPath = resolve(process.cwd(), '.env')
  if (existsSync(envPath)) {
    const overwrite = checkCancel(await p.confirm({
      message: chalk.yellow('.env dosyası zaten mevcut. Üzerine yazmak istiyor musunuz?'),
      initialValue: false,
    }))
    if (!overwrite) cancel('Mevcut yapılandırma korundu.')
  }

  // ─ Step 1: Company info ───────────────────────────────────────────────────
  p.log.step(chalk.bold('Adım 1 / 4') + chalk.dim(' — Şirket Bilgileri'))

  const companyName = checkCancel(await p.text({
    message: 'Şirket adı',
    placeholder: 'Acme Corp',
    validate: (v) => v.trim().length === 0 ? 'Şirket adı boş bırakılamaz.' : undefined,
  }))

  const sector = checkCancel(await p.text({
    message: 'Sektör ' + chalk.dim('(opsiyonel)'),
    placeholder: 'Yazılım & SaaS',
  }))

  const website = checkCancel(await p.text({
    message: 'Website ' + chalk.dim('(opsiyonel)'),
    placeholder: 'https://example.com',
  }))

  // ─ Step 2: AI Providers ───────────────────────────────────────────────────
  p.log.step(chalk.bold('Adım 2 / 4') + chalk.dim(' — AI Sağlayıcıları'))
  p.log.info('Boş bırakarak sağlayıcıları atlayabilirsiniz. Kurulum sonrası da eklenebilir.')

  const configuredProviders: Record<string, string> = {}
  let configuredCount = 0

  for (const provider of PROVIDERS) {
    const raw = checkCancel(await p.password({
      message: chalk.cyan(provider.displayName) + ' API Key' + chalk.dim(' (atlamak için boş bırakın)'),
    }))

    const key = String(raw).trim()
    if (!key) {
      p.log.warn(`${provider.displayName} atlandı`)
      continue
    }

    const spin = p.spinner()
    spin.start(`${provider.displayName} bağlantısı test ediliyor...`)

    const valid = await testProviderKey(provider.id, key)

    if (valid) {
      spin.stop(chalk.green(`✓ ${provider.displayName} — bağlantı başarılı`))
      configuredProviders[provider.envKey] = key
      configuredCount++
    } else {
      spin.stop(chalk.red(`✗ ${provider.displayName} — geçersiz veya erişilemiyor (key kaydedilmedi)`))
    }
  }

  if (configuredCount === 0) {
    p.log.warn(
      'Hiçbir AI sağlayıcısı yapılandırılmadı.\n' +
      '  Platform başladıktan sonra Ayarlar → Sağlayıcılar ekranından ekleyebilirsiniz.'
    )
  }

  // ─ Step 3: Server settings ────────────────────────────────────────────────
  p.log.step(chalk.bold('Adım 3 / 4') + chalk.dim(' — Sunucu Ayarları'))

  const port = checkCancel(await p.text({
    message: 'Backend portu',
    initialValue: '8000',
    validate: (v) => (isNaN(Number(v)) || Number(v) < 1 || Number(v) > 65535)
      ? 'Geçerli bir port numarası girin (1–65535).'
      : undefined,
  }))

  const dataDir = checkCancel(await p.text({
    message: 'Veri dizini',
    initialValue: './data',
    validate: (v) => v.trim().length === 0 ? 'Veri dizini boş bırakılamaz.' : undefined,
  }))

  // ─ Step 4: Write .env ─────────────────────────────────────────────────────
  p.log.step(chalk.bold('Adım 4 / 4') + chalk.dim(' — Yapılandırma Yazılıyor'))

  const spin = p.spinner()
  spin.start('.env dosyası oluşturuluyor...')

  writeEnv({
    companyName: String(companyName),
    sector:      String(sector),
    website:     String(website),
    port:        String(port),
    dataDir:     String(dataDir),
    providers:   configuredProviders,
  })

  spin.stop(chalk.green('✓ .env dosyası oluşturuldu'))

  // ─ Summary ────────────────────────────────────────────────────────────────
  const activeProviders = Object.keys(configuredProviders)

  console.log()
  p.note(
    [
      chalk.bold('Şirket:   ') + companyName,
      chalk.bold('Port:     ') + port,
      chalk.bold('Veri:     ') + dataDir,
      chalk.bold('Sağlayıcı:') + (activeProviders.length > 0
        ? ' ' + activeProviders.join(', ').replace(/_API_KEY/g, '').toLowerCase()
        : chalk.dim(' —')),
    ].join('\n'),
    'Özet'
  )

  p.outro(
    chalk.green.bold('✓ Kurulum tamamlandı!\n\n') +
    '  Platformu başlatmak için:\n\n' +
    chalk.cyan('    cd /root/projects/3rdparty-agent-org\n') +
    chalk.cyan('    docker compose up\n\n') +
    chalk.dim('  veya ayrı terminallerde:\n') +
    chalk.dim('    backend → uvicorn main:app --port 8000\n') +
    chalk.dim('    frontend → npm run dev')
  )
}
