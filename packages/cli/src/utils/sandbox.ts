/**
 * Locate the `sandbox/` assets (`compose.yaml`, `Dockerfile`, `egress/`) that
 * `3pa run` launches (ADR-0002 / ADR-0009).
 *
 * For now these live in this repo. `FABAGENT_SANDBOX_DIR` overrides the search
 * (a packaged `3pa` binary will bundle them — ADR-0012).
 */

import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export function findSandboxDir(): string {
  const override = process.env.FABAGENT_SANDBOX_DIR
  if (override) {
    if (!existsSync(resolve(override, 'compose.yaml'))) {
      throw new Error(`FABAGENT_SANDBOX_DIR has no compose.yaml: ${override}`)
    }
    return resolve(override)
  }

  // Walk up from this file (packages/cli/src/utils) and from cwd.
  const starts = [dirname(fileURLToPath(import.meta.url)), process.cwd()]
  for (const start of starts) {
    let dir = start
    for (let i = 0; i < 8; i++) {
      const candidate = resolve(dir, 'sandbox', 'compose.yaml')
      if (existsSync(candidate)) return resolve(dir, 'sandbox')
      const parent = resolve(dir, '..')
      if (parent === dir) break
      dir = parent
    }
  }
  throw new Error(
    'could not find sandbox/compose.yaml — set FABAGENT_SANDBOX_DIR to its directory',
  )
}
