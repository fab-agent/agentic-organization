// Child process for the crash test: replays a recorded platform and dies (exit 73) in the
// middle of the activation, so nothing in this process can run a catch or an undo.
import { readFileSync, renameSync } from 'node:fs'

import { syncWorkspace } from '../../src/utils/provisioner.ts'

const cfg = JSON.parse(readFileSync(process.argv[2]!, 'utf8')) as {
  replay: Record<string, { status: number; body: string }>
  baseUrl: string; rootPub: string; appHome: string; stateDir: string; now: number; crashAtRename: number
}
let n = 0
const fetchImpl: typeof fetch = async (url) => {
  const u = new URL(String(url))
  const r = cfg.replay[u.pathname]
  if (!r) return new Response('{}', { status: 404 })
  return new Response(Buffer.from(r.body, 'base64'), { status: r.status })
}
await syncWorkspace({
  baseUrl: cfg.baseUrl, webToken: 't', rootPub: cfg.rootPub, appHome: cfg.appHome, stateDir: cfg.stateDir,
  clientVersion: '1.0.0', now: () => cfg.now, fetchImpl,
  fsOps: {
    rename: (a: string, b: string) => {
      if (++n === cfg.crashAtRename) process.exit(73) // power loss / kill -9, before this rename
      renameSync(a, b)
    },
  },
})
