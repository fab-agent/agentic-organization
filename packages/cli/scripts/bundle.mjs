/**
 * Bundle `3pa` into a single self-contained ESM file for release (ADR-0012).
 * `cross-spawn` (via execa) does a runtime `require('child_process')`, so the
 * ESM banner shims `require` / `__dirname` / `__filename`.
 */
import * as esbuild from 'esbuild'

await esbuild.build({
  entryPoints: ['src/index.ts'],
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node20',
  outfile: 'dist/3pa.mjs',
  banner: {
    js: [
      '#!/usr/bin/env node',
      "import { createRequire as ___cr } from 'node:module'",
      "import { fileURLToPath as ___f } from 'node:url'",
      "import { dirname as ___d } from 'node:path'",
      'const require = ___cr(import.meta.url)',
      'const __filename = ___f(import.meta.url)',
      'const __dirname = ___d(__filename)',
    ].join('\n'),
  },
})

console.log('bundled → dist/3pa.mjs')
