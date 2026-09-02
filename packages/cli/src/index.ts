import chalk from 'chalk'
import { audit   } from './commands/audit.js'
import { doctor  } from './commands/doctor.js'
import { init    } from './commands/init.js'
import { login   } from './commands/login.js'
import { logout  } from './commands/logout.js'
import { policy  } from './commands/policy.js'
import { refresh } from './commands/refresh.js'
import { run     } from './commands/run.js'
import { start   } from './commands/start.js'
import { status  } from './commands/status.js'

const [, , cmd, ...args] = process.argv

switch (cmd) {
  case 'init':
    await init()
    break

  case 'login':
    await login(args)
    break

  case 'logout':
    await logout(args)
    break

  case 'refresh':
    await refresh()
    break

  case 'run':
    await run(args)
    break

  case 'policy':
    await policy(args)
    break

  case 'audit':
    await audit(args)
    break

  case 'doctor':
    await doctor()
    break

  case 'start':
    await start()
    break

  case 'status':
    await status()
    break

  case '--version':
  case '-v':
    console.log('0.1.0')
    break

  default: {
    const unknown = cmd ? chalk.red(`\n  Bilinmeyen komut: ${chalk.bold(cmd)}\n`) : ''
    console.log(unknown)
    console.log(chalk.bold('  3rdParty Agent CLI') + chalk.dim(' v0.1.0'))
    console.log()
    console.log('  ' + chalk.bold('Kullanım:') + '  3pa <komut>')
    console.log()
    console.log('  ' + chalk.cyan('3pa init  ') + '   Kurulum sihirbazını başlat')
    console.log('  ' + chalk.cyan('3pa login ') + '   Persona seç ve workstation token al')
    console.log('  ' + chalk.cyan('3pa logout') + '   Yerel oturumu kapat (--revoke: sunucuda da iptal et)')
    console.log('  ' + chalk.cyan('3pa refresh') + '  Persona access token\'ı yenile')
    console.log('  ' + chalk.cyan('3pa run   ') + '   opencode\'u yönetilen sandbox içinde başlat')
    console.log('  ' + chalk.cyan('3pa policy') + '   Persona için etkin policy kurallarını göster')
    console.log('  ' + chalk.cyan('3pa audit verify') + ' Sunucudaki audit zincirini doğrula')
    console.log('  ' + chalk.cyan('3pa doctor') + '   Sandbox ön koşullarını kontrol et')
    console.log('  ' + chalk.cyan('3pa start ') + '   Platformu Docker ile başlat')
    console.log('  ' + chalk.cyan('3pa status') + '   Platform durumunu göster')
    console.log()
    if (cmd && cmd !== '--help' && cmd !== '-h') process.exit(1)
  }
}
