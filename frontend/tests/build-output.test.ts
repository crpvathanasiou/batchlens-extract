import { readFile, readdir, rm } from 'node:fs/promises'
import { resolve } from 'node:path'
import { afterAll, describe, expect, it } from 'vitest'
import { build, type UserConfig } from 'vite'
import configured from '../vite.config'

const output = resolve('.test-build')
afterAll(() => rm(output, { recursive: true, force: true }))

describe('production library output', () => {
  it('emits exact entry names and a self-hosted worker URL', async () => {
    const config = configured as UserConfig
    await build({
      ...config,
      configFile: false,
      logLevel: 'silent',
      build: { ...config.build, outDir: output },
    })
    const files = await readdir(output)
    const assets = await readdir(resolve(output, 'assets'))
    const javascript = await readFile(resolve(output, 'review.js'), 'utf8')

    expect(files).toEqual(expect.arrayContaining(['review.js', 'review.css', 'assets']))
    expect(assets.some((name) => /^pdf\.worker\.min-.+\.mjs$/.test(name))).toBe(true)
    expect(javascript).toContain('/documents/review-assets/assets/pdf.worker.min-')
    expect(javascript).not.toContain('data:application')
  }, 30_000)
})
