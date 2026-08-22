import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(scriptDirectory, '..')
const sourceRoot = path.join(frontendRoot, 'src')
const policyPath = path.join(frontendRoot, 'ui-policy.json')
const outputPath = path.join(sourceRoot, 'generated', 'styleBaseline.ts')

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name)
    return entry.isDirectory() ? walk(target) : [target]
  })
}

function relativeSource(target) {
  return path.relative(frontendRoot, target).split(path.sep).join('/')
}

function addClass(classes, className, source, kind) {
  if (!className || className === 'bi') return
  const record = classes.get(className) ?? {
    name: className,
    usageCount: 0,
    sources: new Set(),
    cssFiles: new Set(),
    kinds: new Set(),
  }
  if (kind === 'template') record.usageCount += 1
  if (kind === 'css') record.cssFiles.add(source)
  record.sources.add(source)
  record.kinds.add(kind)
  classes.set(className, record)
}

function scanTemplateClasses(source, file, classes) {
  for (const match of source.matchAll(/\bclass\s*=\s*["']([^"']+)["']/g)) {
    for (const className of match[1].split(/\s+/)) addClass(classes, className, file, 'template')
  }
}

function scanCssClasses(source, file, classes) {
  for (const match of source.matchAll(/([^{}]+)\{/g)) {
    const selector = match[1].trim()
    if (selector.startsWith('@')) continue
    for (const selectorPart of selector.split(',')) {
      for (const className of selectorPart.matchAll(/\.([A-Za-z_][\w-]*)/g)) {
        addClass(classes, className[1], file, 'css')
      }
    }
  }
}

function scanComponents(source, file, components, policy) {
  for (const match of source.matchAll(/<((?:Lte)[A-Z][A-Za-z0-9]*)\b([^>]*)>/g)) {
    const name = match[1]
    const attributes = match[2]
    const record = components.get(name) ?? {
      name,
      usageCount: 0,
      variants: new Set(),
      sources: new Set(),
      approved: policy.adminLteVue.allowedImports.includes(name)
        || Object.hasOwn(policy.adminLteVue.controlledImports ?? {}, name),
    }
    record.usageCount += 1
    record.sources.add(file)
    const variantParts = []
    for (const prop of ['theme', 'size']) {
      const value = attributes.match(new RegExp(`(?:^|\\s)${prop}=["']([^"']+)["']`))?.[1]
      if (value) variantParts.push(`${prop}=${value}`)
    }
    if (variantParts.length) record.variants.add(variantParts.join(', '))
    components.set(name, record)
  }
}

function buildBaseline() {
  const policy = JSON.parse(fs.readFileSync(policyPath, 'utf8'))
  const classRecipes = new Map()
  for (const recipe of policy.styles.classRecipes ?? []) {
    for (const className of recipe.classes ?? []) {
      const recipes = classRecipes.get(className) ?? []
      recipes.push(recipe.name)
      classRecipes.set(className, recipes)
    }
  }

  const classes = new Map()
  const components = new Map()
  const sourceFiles = walk(sourceRoot).filter((file) => {
    const relative = relativeSource(file)
    return !relative.includes('/generated/') && !relative.endsWith('.test.ts')
  })

  for (const file of sourceFiles) {
    const relative = relativeSource(file)
    const source = fs.readFileSync(file, 'utf8')
    if (file.endsWith('.vue')) {
      scanTemplateClasses(source, relative, classes)
      scanComponents(source, relative, components, policy)
    }
    if (file.endsWith('.css') && (policy.styles.allowedProjectCss ?? []).includes(relative)) {
      scanCssClasses(source, relative, classes)
    }
  }

  const classInventory = [...classes.values()].map((record) => ({
    name: record.name,
    usageCount: record.usageCount,
    sources: [...record.sources].sort(),
    cssFiles: [...record.cssFiles].sort(),
    kinds: [...record.kinds].sort(),
    recipes: classRecipes.get(record.name) ?? [],
    status: classRecipes.has(record.name)
      || (record.name.startsWith('bi-') && policy.icons.allowed.includes(record.name.slice(3)))
      ? 'registered'
      : (record.name === 'selected' || record.name.startsWith('vue-flow__'))
        ? 'external'
        : 'suspect',
    approved: classRecipes.has(record.name)
      || (record.name.startsWith('bi-') && policy.icons.allowed.includes(record.name.slice(3)))
      || record.name === 'selected'
      || record.name.startsWith('vue-flow__'),
  })).sort((left, right) => left.name.localeCompare(right.name))
  const componentInventory = [...components.values()].map((record) => ({
    name: record.name,
    usageCount: record.usageCount,
    variants: [...record.variants].sort(),
    sources: [...record.sources].sort(),
    approved: record.approved,
  })).sort((left, right) => left.name.localeCompare(right.name))

  return {
    generatedFrom: ['ui-policy.json', 'src/**/*.vue', 'src/styles/*.css'],
    classInventory,
    componentInventory,
    summary: {
      classCount: classInventory.length,
      usedClassCount: classInventory.filter((item) => item.usageCount > 0).length,
      suspectClassCount: classInventory.filter((item) => item.status === 'suspect').length,
      componentCount: componentInventory.length,
      suspectComponentCount: componentInventory.filter((item) => !item.approved).length,
    },
  }
}

const baseline = buildBaseline()
fs.mkdirSync(path.dirname(outputPath), { recursive: true })
fs.writeFileSync(
  outputPath,
  `// Generated by scripts/generate-style-baseline.mjs. Do not edit by hand.\nexport const styleBaseline = ${JSON.stringify(baseline, null, 2)} as const\n`,
  'utf8',
)
console.log(`Style baseline generated: ${relativeSource(outputPath)} (${baseline.summary.classCount} classes, ${baseline.summary.componentCount} AdminLTE components).`)
