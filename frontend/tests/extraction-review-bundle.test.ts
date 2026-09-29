import { readFile, rm } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, describe, expect, it } from 'vitest'
import { build, type UserConfig } from 'vite'
import configured from '../vite.config'

const output = resolve('.test-build-extraction-export')
const here = dirname(fileURLToPath(import.meta.url))

afterAll(() => rm(output, { recursive: true, force: true }))

describe('extraction review library export', () => {
  it('exports the local-harness bootstrap import from the built module', async () => {
    const harness = await readFile(
      resolve(here, '../../tests/extraction_review/local_harness.py'),
      'utf8',
    )
    const imported = harness.match(/import \{ ([A-Za-z_][A-Za-z0-9_]*) \}/)
    const importedName = imported?.[1]
    expect(importedName).toBe('mountExtractionReviewWorkspace')
    expect(harness).toContain("from '/documents/review-assets/review.js'")
    expect(harness).toContain(`${importedName}('#extraction-review'`)

    const config = configured as UserConfig
    await build({
      ...config,
      configFile: false,
      logLevel: 'silent',
      build: { ...config.build, outDir: output },
    })

    const javascript = await readFile(resolve(output, 'review.js'), 'utf8')
    const exported = libraryExportNames(javascript)
    expect(exported.has(importedName ?? '')).toBe(true)
    expect(exported.has('mountReviewWorkspace')).toBe(true)
  }, 30_000)
})

function libraryExportNames(javascript: string): Set<string> {
  const names = new Set<string>()
  for (const match of javascript.matchAll(/^export\s*\{([^}]+)\}\s*;?/gm)) {
    for (const part of match[1].split(',')) {
      const alias = part.trim().match(/^(?:[A-Za-z_$][\w$]*\s+as\s+)?([A-Za-z_$][\w$]*)$/)
      if (alias?.[1]) names.add(alias[1])
    }
  }
  for (const match of javascript.matchAll(/^export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/gm)) {
    if (match[1]) names.add(match[1])
  }
  return names
}
