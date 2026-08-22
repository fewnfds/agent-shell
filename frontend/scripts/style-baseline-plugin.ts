import fs from 'node:fs'
import path from 'node:path'

import type { Plugin } from 'vite'

const moduleId = 'virtual:style-baseline'
const resolvedModuleId = `\0${moduleId}`

type ClassRecord = {
  name: string
  usageCount: number
  sources: Set<string>
}

type UiPolicy = {
  icons: { allowed: string[] }
  styles: {
    allowedProjectCss: string[]
    classRecipes: Array<{ name: string; classes: string[] }>
  }
}

function walk(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name)
    return entry.isDirectory() ? walk(target) : [target]
  })
}

function sourcePath(frontendRoot: string, target: string): string {
  return path.relative(frontendRoot, target).split(path.sep).join('/')
}

function addClass(classes: Map<string, ClassRecord>, name: string, source: string, used: boolean): void {
  if (!name || name === 'bi') return
  const record = classes.get(name) ?? { name, usageCount: 0, sources: new Set<string>() }
  if (used) record.usageCount += 1
  record.sources.add(source)
  classes.set(name, record)
}

function scanVue(source: string, file: string, classes: Map<string, ClassRecord>): void {
  for (const match of source.matchAll(/\bclass\s*=\s*["']([^"']+)["']/g)) {
    for (const name of match[1].split(/\s+/)) addClass(classes, name, file, true)
  }
}

function scanCss(source: string, file: string, classes: Map<string, ClassRecord>): void {
  for (const match of source.matchAll(/([^{}]+)\{/g)) {
    const selector = match[1].trim()
    if (selector.startsWith('@')) continue
    for (const selectorPart of selector.split(',')) {
      for (const className of selectorPart.matchAll(/\.([A-Za-z_][\w-]*)/g)) {
        addClass(classes, className[1], file, false)
      }
    }
  }
}

function buildBaseline(frontendRoot: string) {
  const sourceRoot = path.join(frontendRoot, 'src')
  const policyPath = path.join(frontendRoot, 'ui-policy.json')
  const policy = JSON.parse(fs.readFileSync(policyPath, 'utf8')) as UiPolicy
  const recipesByClass = new Map<string, string[]>()

  for (const recipe of policy.styles.classRecipes) {
    for (const className of recipe.classes) {
      const recipes = recipesByClass.get(className) ?? []
      recipes.push(recipe.name)
      recipesByClass.set(className, recipes)
    }
  }

  const classes = new Map<string, ClassRecord>()
  const sourceFiles = walk(sourceRoot).filter((file) => {
    const relative = sourcePath(frontendRoot, file)
    return !relative.endsWith('.test.ts')
      && (file.endsWith('.vue') || policy.styles.allowedProjectCss.includes(relative))
  })

  for (const file of sourceFiles) {
    const relative = sourcePath(frontendRoot, file)
    const source = fs.readFileSync(file, 'utf8')
    if (file.endsWith('.vue')) scanVue(source, relative, classes)
    else scanCss(source, relative, classes)
  }

  const classInventory = [...classes.values()].map((record) => {
    const recipes = recipesByClass.get(record.name) ?? []
    const registered = recipes.length > 0
      || (record.name.startsWith('bi-') && policy.icons.allowed.includes(record.name.slice(3)))
    const external = record.name === 'selected' || record.name.startsWith('vue-flow__')
    return {
      name: record.name,
      usageCount: record.usageCount,
      sources: [...record.sources].sort(),
      recipes,
      status: registered ? 'registered' : external ? 'external' : 'suspect',
      approved: registered || external,
    }
  }).sort((left, right) => left.name.localeCompare(right.name))

  const componentNames = new Set<string>()
  for (const file of sourceFiles.filter((item) => item.endsWith('.vue'))) {
    const source = fs.readFileSync(file, 'utf8')
    for (const match of source.matchAll(/<((?:Lte)[A-Z][A-Za-z0-9]*)\b/g)) componentNames.add(match[1])
  }

  return {
    classInventory,
    summary: {
      classCount: classInventory.length,
      usedClassCount: classInventory.filter((item) => item.usageCount > 0).length,
      suspectClassCount: classInventory.filter((item) => item.status === 'suspect').length,
      componentCount: componentNames.size,
    },
    watchedFiles: [policyPath, ...sourceFiles],
  }
}

export function styleBaselinePlugin(frontendRoot: string): Plugin {
  return {
    name: 'agent-shell-style-baseline',
    resolveId(id) {
      return id === moduleId ? resolvedModuleId : undefined
    },
    load(id) {
      if (id !== resolvedModuleId) return undefined
      const { watchedFiles, ...baseline } = buildBaseline(frontendRoot)
      for (const file of watchedFiles) this.addWatchFile(file)
      return `export const styleBaseline = ${JSON.stringify(baseline)}`
    },
  }
}
