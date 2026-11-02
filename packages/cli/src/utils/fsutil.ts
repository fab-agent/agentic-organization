/**
 * Small file helpers the provisioner depends on for correctness.
 *
 * `writeSync` may write fewer bytes than asked (a full disk, a signal, some file systems),
 * and returns how many it wrote; ignoring that leaves a truncated file that still looks
 * successfully written. Everything that matters here goes through `writeAll`.
 */

import {
  closeSync, fstatSync, fsyncSync, lstatSync, openSync, renameSync, rmSync, writeSync,
} from 'node:fs'
import { randomBytes } from 'node:crypto'
import { dirname } from 'node:path'

export class FsError extends Error {
  code: string
  constructor(code: string) {
    super(code)
    this.code = code
  }
}

/** Write the whole buffer, or throw. Zero progress is an error, never a retry loop. */
export function writeAll(
  fd: number,
  data: Uint8Array,
  write: (fd: number, buf: Uint8Array, off: number, len: number) => number = writeSync,
): void {
  let off = 0
  while (off < data.length) {
    const n = write(fd, data, off, data.length - off)
    if (n <= 0) throw new FsError('write_failed')
    off += n
  }
}

/** Best effort: not every platform or file system lets a directory be synced. */
export function fsyncDir(dir: string): void {
  try {
    const fd = openSync(dir, 'r')
    try {
      fsyncSync(fd)
    } finally {
      closeSync(fd)
    }
  } catch {
    /* ignore */
  }
}

/** Create a new file exclusively (never over an existing path), write all of it, check
 * the size on disk, flush. */
export function createFileExclusive(
  path: string,
  data: Uint8Array,
  mode = 0o600,
  write?: Parameters<typeof writeAll>[2],
): void {
  const fd = openSync(path, 'wx', mode)
  try {
    writeAll(fd, data, write)
    if (fstatSync(fd).size !== data.length) throw new FsError('write_failed')
    fsyncSync(fd)
  } finally {
    closeSync(fd)
  }
}

/** Replace `path` atomically: temp file in the same directory, full write, fsync, rename,
 * then sync the directory so the rename itself survives a crash. */
export function writeFileAtomic(
  path: string,
  data: string | Uint8Array,
  mode = 0o600,
  rename: (from: string, to: string) => void = renameSync,
): void {
  const buf = typeof data === 'string' ? Buffer.from(data, 'utf8') : data
  const tmp = `${path}.${randomBytes(6).toString('hex')}.tmp`
  try {
    createFileExclusive(tmp, buf, mode)
    rename(tmp, path)
  } catch (e) {
    rmSync(tmp, { force: true })
    throw e
  }
  fsyncDir(dirname(path))
}

/** True when something is at `path`, including a dangling link (existsSync follows links
 * and says false for those). */
export function lexists(path: string): boolean {
  try {
    lstatSync(path)
    return true
  } catch {
    return false
  }
}
