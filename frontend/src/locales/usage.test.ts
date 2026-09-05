import { readdirSync, readFileSync } from 'node:fs'
import { extname, join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { blockTypes } from '@/domain/blocks'
import { messageKeys } from './index'
import { zhCN } from './zh-CN'

const srcRoot = join(process.cwd(), 'src')
const backendRoot = join(process.cwd(), '..', 'server', 'src', 'agent_shell')
const nonLocaleDottedLiterals = new Set([
  'fields.length',
  'models.length',
])

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return ['.py', '.ts', '.vue'].includes(extname(entry.name)) && !entry.name.endsWith('.test.ts')
      ? [path]
      : []
  })
}

function staticLocaleKeys(): string[] {
  const catalog = new Set(messageKeys(zhCN))
  const roots = new Set(messageKeys(zhCN).map((key) => key.split('.')[0]))
  const candidates = new Set<string>()
  const stringLiteral = /['"`]([A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)+)['"`]/g

  for (const file of sourceFiles(srcRoot)) {
    const source = readFileSync(file, 'utf8')
    for (const match of source.matchAll(stringLiteral)) {
      const key = match[1]
      if (
        key
        && roots.has(key.split('.')[0])
        && !key.includes('${')
        && !nonLocaleDottedLiterals.has(key)
      ) candidates.add(key)
    }
  }
  return [...candidates].filter((key) => !catalog.has(key)).sort()
}

function backendMessageKeys(): string[] {
  const candidates = new Set<string>()
  const messageKey = /['"]((?:errors|resource|validation)(?:\.[A-Za-z][A-Za-z0-9]*)+)['"]/g
  const generatedAuthoringError = /(?:PythonPackageAuthoringError|SkillPackageAuthoringError)\(\s*['"]([a-z][a-z0-9_]*)['"]/g
  for (const file of sourceFiles(backendRoot)) {
    const source = readFileSync(file, 'utf8')
    for (const match of source.matchAll(messageKey)) {
      if (match[1]) candidates.add(match[1])
    }
    for (const match of source.matchAll(generatedAuthoringError)) {
      if (!match[1]) continue
      const [first, ...rest] = match[1].split('_')
      candidates.add(`errors.${first}${rest.map((part) => (
        part.charAt(0).toUpperCase() + part.slice(1)
      )).join('')}`)
    }
  }
  return [...candidates].sort()
}

describe('locale usage', () => {
  it('defines every statically referenced locale key', () => {
    expect(staticLocaleKeys()).toEqual([])
  })

  it('defines every catalog-driven capability and editor key', () => {
    const catalog = new Set(messageKeys(zhCN))
    for (const type of blockTypes) {
      expect(catalog.has(`capabilities.${type}.label`)).toBe(true)
    }
    for (const policy of ['inherit', 'force-remove', 'top-level-only']) {
      expect(catalog.has(`agents.policy.${policy}`)).toBe(true)
    }
  })

  it('defines every message key emitted by the backend', () => {
    const catalog = new Set(messageKeys(zhCN))
    expect(backendMessageKeys().filter((key) => !catalog.has(key))).toEqual([])
  })
})
