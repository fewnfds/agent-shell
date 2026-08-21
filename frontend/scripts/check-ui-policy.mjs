#!/usr/bin/env node

import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { baseParse, NodeTypes, parserOptions } from '@vue/compiler-dom'
import { parse as parseSfc } from '@vue/compiler-sfc'
import ts from 'typescript'

function normalizePath(value) {
  return value.split(path.sep).join('/')
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

function collectFiles(directory, extensions) {
  if (!fs.existsSync(directory)) return []
  const files = []
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist') continue
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) files.push(...collectFiles(fullPath, extensions))
    else if (extensions.some((extension) => entry.name.endsWith(extension))) files.push(fullPath)
  }
  return files
}

function globToRegExp(pattern) {
  let result = '^'
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index]
    if (char === '*') {
      if (pattern[index + 1] === '*') {
        result += '.*'
        index += 1
      } else {
        result += '[^/]*'
      }
    } else if (char === '?') {
      result += '[^/]'
    } else {
      result += char.replace(/[|\\{}()[\]^$+?.]/g, '\\$&')
    }
  }
  return new RegExp(`${result}$`)
}

function matchesAny(file, patterns = []) {
  return patterns.some((pattern) => globToRegExp(pattern).test(file))
}

function sourceLine(source, offset) {
  return source.slice(0, offset).split(/\r?\n/).length
}

function resolveVueImport(root, importer, specifier) {
  let candidate
  if (specifier.startsWith('@/')) candidate = path.join(root, 'src', specifier.slice(2))
  else if (specifier.startsWith('.')) candidate = path.resolve(root, path.dirname(importer), specifier)
  else return null
  if (!path.extname(candidate)) candidate += '.vue'
  if (!candidate.endsWith('.vue')) return null
  return normalizePath(path.relative(root, candidate))
}

function importName(importSpecifier) {
  if (ts.isImportSpecifier(importSpecifier)) return importSpecifier.propertyName?.text ?? importSpecifier.name.text
  return null
}

function checkWorkspace(root, policyPath) {
  const policy = readJson(policyPath)
  const packageJson = readJson(path.join(root, 'package.json'))
  const errors = []
  const warnings = []
  const importGraph = new Map()
  const dependencies = packageJson.dependencies ?? {}
  const devDependencies = packageJson.devDependencies ?? {}
  const allDirectDependencies = { ...devDependencies, ...dependencies }
  const relative = (file) => normalizePath(path.relative(root, file))
  const addError = (file, message, line) => {
    errors.push(`${file}${line ? `:${line}` : ''} ${message}`)
  }

  for (const [name, expected] of Object.entries(policy.dependencies.requiredExact ?? {})) {
    const actual = allDirectDependencies[name]
    if (actual !== expected) addError('package.json', `requires exact ${name}@${expected}; found ${actual ?? 'missing'}`)
  }

  const approvedRuntime = new Set([
    ...(policy.dependencies.approvedRuntime ?? []),
    ...(policy.migration.temporaryRuntimeDependencies ?? []),
  ])
  for (const name of Object.keys(dependencies)) {
    if (!approvedRuntime.has(name)) addError('package.json', `unapproved runtime dependency "${name}"`)
  }
  for (const name of policy.dependencies.forbidden ?? []) {
    if (name in allDirectDependencies) addError('package.json', `forbidden dependency "${name}" is installed directly`)
  }

  const migrationPaths = [
    ...(policy.migration.legacyVuePaths ?? []),
    ...(policy.migration.legacyElementImportPaths ?? []),
    ...(policy.migration.legacyCssPaths ?? []),
  ]
  for (const migrationPath of migrationPaths) {
    if (!fs.existsSync(path.join(root, migrationPath))) addError('ui-policy.json', `stale migration exception "${migrationPath}"`)
  }

  const approvedComponents = new Map(
    (policy.localComponents.approved ?? []).map((item) => [item.path, item]),
  )
  const adminAllowed = new Set(policy.adminLteVue.allowedImports ?? [])
  const adminTypeAllowed = new Set(policy.adminLteVue.allowedTypeImports ?? [])
  const adminForbidden = new Set(policy.adminLteVue.forbiddenImports ?? [])
  const controlled = policy.adminLteVue.controlledImports ?? {}

  function adminImportAllowed(name, file) {
    if (adminAllowed.has(name) || adminTypeAllowed.has(name)) return true
    if ((policy.testing?.adminLteIntegrationPaths ?? []).includes(file) && Object.hasOwn(controlled, name)) return true
    return (controlled[name] ?? []).includes(file)
  }

  function scanScript(source, file, sourceOffset = 0) {
    const scriptKind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
    const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, scriptKind)
    const imports = importGraph.get(file) ?? new Set()
    importGraph.set(file, imports)

    if (source.includes('element-plus') && !(policy.migration.legacyElementImportPaths ?? []).includes(file)) {
      addError(file, 'Element Plus reference is forbidden outside the shrinking migration allowlist')
    }

    for (const statement of sourceFile.statements) {
      if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue
      const moduleName = statement.moduleSpecifier.text
      const line = sourceLine(source, statement.getStart(sourceFile)) + sourceLine(source, sourceOffset) - 1

      const resolvedVue = resolveVueImport(root, file, moduleName)
      if (resolvedVue) imports.add(resolvedVue)

      if (moduleName === '@adminlte/vue/plugins' || moduleName.startsWith('@adminlte/vue/plugins/')) {
        addError(file, 'importing @adminlte/vue/plugins is forbidden', line)
        continue
      }
      if (moduleName === '@adminlte/vue/css') {
        if (!(policy.adminLteVue.cssImportPaths ?? []).includes(file)) {
          addError(file, '@adminlte/vue/css may only be imported by the policy CSS entry', line)
        }
        continue
      }
      if (moduleName.startsWith('@adminlte/vue/') && moduleName !== '@adminlte/vue') {
        addError(file, `unsupported AdminLTE subpath import "${moduleName}"`, line)
        continue
      }
      if (moduleName === 'bootstrap-icons/font/bootstrap-icons.css') {
        if (!(policy.icons.cssImportPaths ?? []).includes(file)) {
          addError(file, 'Bootstrap Icons CSS may only be imported by the policy icon entry', line)
        }
        continue
      }
      if (moduleName !== '@adminlte/vue') continue

      const clause = statement.importClause
      if (!clause) continue
      if (clause.name) addError(file, 'default AdminLTE import/global registration is forbidden; use named imports', line)
      if (clause.namedBindings && ts.isNamespaceImport(clause.namedBindings)) {
        addError(file, 'namespace AdminLTE imports are forbidden; use named imports', line)
      }
      if (!clause.namedBindings || !ts.isNamedImports(clause.namedBindings)) continue
      for (const specifier of clause.namedBindings.elements) {
        const name = importName(specifier)
        if (!name) continue
        if (adminForbidden.has(name)) addError(file, `AdminLTE import "${name}" is explicitly forbidden`, line)
        else if (!adminImportAllowed(name, file)) addError(file, `AdminLTE import "${name}" is not approved for this path`, line)
      }
    }

    if ((policy.icons.staticSourcePaths ?? []).includes(file)) {
      function visitIconLiteral(node) {
        if (ts.isStringLiteralLike(node) && /^bi-[a-z0-9-]+$/.test(node.text)) {
          const line = sourceLine(source, node.getStart(sourceFile)) + sourceLine(source, sourceOffset) - 1
          validateIcon(file, node.text, line)
        }
        ts.forEachChild(node, visitIconLiteral)
      }
      visitIconLiteral(sourceFile)
    }
  }

  function allowedClassesFor(file) {
    const values = new Set()
    for (const recipe of policy.styles.classRecipes ?? []) {
      if (matchesAny(file, recipe.paths ?? [])) {
        for (const className of recipe.classes ?? []) values.add(className)
      }
    }
    return values
  }

  function validateIcon(file, icon, line) {
    const normalized = icon.replace(/^bi-/, '')
    if (!(policy.icons.allowed ?? []).includes(normalized)) {
      addError(file, `Bootstrap icon "${icon}" is not approved`, line)
    }
  }

  function scanTemplate(template, file) {
    let ast
    try {
      ast = baseParse(template, parserOptions)
    } catch (error) {
      addError(file, `template parse failed: ${error instanceof Error ? error.message : String(error)}`)
      return
    }
    const allowedClasses = allowedClassesFor(file)
    const controlSemantics = policy.styles.controlSemantics ?? {}
    const visibleLabelClass = controlSemantics.visibleLabelClass
    const hiddenLabelClass = controlSemantics.hiddenLabelClass
    const controlRowAttribute = controlSemantics.controlRowAttribute
    const controlColumnPrefixes = controlSemantics.controlColumnPrefixes ?? []
    const peerLegendClasses = new Set(controlSemantics.peerLegendClasses ?? [])

    function staticClasses(node) {
      if (node.type !== NodeTypes.ELEMENT) return new Set()
      const classAttribute = node.props.find((prop) => (
        prop.type === NodeTypes.ATTRIBUTE && prop.name === 'class'
      ))
      return new Set((classAttribute?.value?.content ?? '').split(/\s+/).filter(Boolean))
    }

    function hasProp(node, name) {
      return node.props.some((prop) => (
        (prop.type === NodeTypes.ATTRIBUTE && prop.name === name)
        || (
          prop.type === NodeTypes.DIRECTIVE
          && prop.name === 'bind'
          && prop.arg?.type === NodeTypes.SIMPLE_EXPRESSION
          && prop.arg.content === name
        )
      ))
    }

    function ownedElementMatches(root, predicate) {
      function search(node, nested) {
        if (node.type !== NodeTypes.ELEMENT) return false
        const classes = staticClasses(node)
        if (nested && (
          classes.has('row')
          || classes.has('card')
          || classes.has('card-header')
          || classes.has('list-group-item')
        )) return false
        if (predicate(node, classes)) return true
        return (node.children ?? []).some((child) => search(child, true))
      }
      return search(root, false)
    }

    function directControlColumns(node) {
      const columns = []
      function collect(children) {
        for (const child of children ?? []) {
          if (child.type !== NodeTypes.ELEMENT) continue
          if (child.tag === 'template') {
            collect(child.children)
            continue
          }
          const classes = staticClasses(child)
          if ([...classes].some((className) => controlColumnPrefixes.some((prefix) => className.startsWith(prefix)))) {
            columns.push(child)
          }
        }
      }
      collect(node.children)
      return columns
    }

    function columnHasFieldLabel(column) {
      return ownedElementMatches(column, (node, classes) => (
        (visibleLabelClass && classes.has(visibleLabelClass))
        || node.tag === 'FormField'
        || (['LteInput', 'LteSelect', 'LteTextarea'].includes(node.tag) && hasProp(node, 'label'))
      ))
    }

    function columnHasSwitch(column) {
      return ownedElementMatches(column, (_node, classes) => classes.has('form-switch'))
    }

    function visit(node) {
      if (node.type === NodeTypes.ELEMENT) {
        const line = node.loc.start.line
        const tag = node.tag
        const classes = staticClasses(node)
        if (tag.startsWith('El')) addError(file, `Element Plus component <${tag}> is forbidden`, line)
        if (tag.startsWith('Lte') && !adminImportAllowed(tag, file)) {
          addError(file, `AdminLTE component <${tag}> is not approved for this path`, line)
        }

        const propRules = policy.adminLteVue.staticPropValues?.[tag] ?? {}
        const forbiddenProps = new Set(policy.adminLteVue.forbiddenProps?.[tag] ?? [])
        for (const prop of node.props) {
          if (prop.type === NodeTypes.ATTRIBUTE) {
            const name = prop.name
            if (name === 'style' && !(policy.styles.allowedInlineStylePaths ?? []).includes(file)) {
              addError(file, 'inline style attributes are forbidden', prop.loc.start.line)
            }
            if (name === 'class') {
              for (const className of (prop.value?.content ?? '').split(/\s+/).filter(Boolean)) {
                if (className === 'bi') continue
                if (className.startsWith('bi-')) validateIcon(file, className, prop.loc.start.line)
                else if (!allowedClasses.has(className)) addError(file, `class "${className}" is outside approved recipes`, prop.loc.start.line)
              }
            }
            if (name === 'icon' && prop.value) validateIcon(file, prop.value.content, prop.loc.start.line)
            if (forbiddenProps.has(name)) addError(file, `visual prop ${tag}.${name} is forbidden`, prop.loc.start.line)
            if (Object.hasOwn(propRules, name)) {
              const value = prop.value?.content
              if (!value || !propRules[name].includes(value)) {
                addError(file, `value "${value ?? ''}" is not approved for ${tag}.${name}`, prop.loc.start.line)
              }
            }
          } else if (prop.type === NodeTypes.DIRECTIVE && prop.arg?.type === NodeTypes.SIMPLE_EXPRESSION) {
            const name = prop.arg.content
            if (prop.name === 'bind' && (name === 'class' || name === 'style')) {
              const allowedInline = name === 'style' && (policy.styles.allowedInlineStylePaths ?? []).includes(file)
              if (!allowedInline) addError(file, `dynamic ${name} bindings are forbidden`, prop.loc.start.line)
            }
            if (prop.name === 'bind' && name === 'icon' && !(policy.icons.dynamicAllowedPaths ?? []).includes(file)) {
              addError(file, 'dynamic icon bindings require an approved path exception', prop.loc.start.line)
            }
            if (prop.name === 'bind' && forbiddenProps.has(name)) {
              addError(file, `visual prop ${tag}.${name} is forbidden`, prop.loc.start.line)
            }
            if (prop.name === 'bind' && Object.hasOwn(propRules, name)) {
              const dynamicPaths = policy.adminLteVue.dynamicPropPaths?.[tag]?.[name] ?? []
              if (!dynamicPaths.includes(file)) {
                addError(file, `dynamic visual prop ${tag}.${name} is forbidden`, prop.loc.start.line)
              }
            }
          }
        }

        if (
          tag === 'legend'
          && [...classes].some((className) => peerLegendClasses.has(className))
          && visibleLabelClass
          && !classes.has(visibleLabelClass)
          && !(hiddenLabelClass && classes.has(hiddenLabelClass))
        ) {
          addError(file, `peer control legend must use Bootstrap .${visibleLabelClass}`, line)
        }

        if (
          classes.has('row')
          && controlRowAttribute
          && hasProp(node, controlRowAttribute)
          && visibleLabelClass
          && controlColumnPrefixes.length > 0
        ) {
          const columns = directControlColumns(node)
          if (columns.length > 1 && columns.some(columnHasFieldLabel)) {
            for (const column of columns) {
              if (columnHasSwitch(column) && !columnHasFieldLabel(column)) {
                addError(file, `switch column beside labelled controls must include .${visibleLabelClass}`, column.loc.start.line)
              }
            }
          }
        }
      }
      for (const child of node.children ?? []) visit(child)
      for (const branch of node.branches ?? []) visit(branch)
    }
    visit(ast)
  }

  const sourceFiles = collectFiles(path.join(root, 'src'), ['.ts', '.tsx', '.js', '.mjs', '.vue'])
  let vueCount = 0
  for (const absoluteFile of sourceFiles) {
    const file = relative(absoluteFile)
    const source = fs.readFileSync(absoluteFile, 'utf8')
    if (!file.endsWith('.vue')) {
      scanScript(source, file)
      continue
    }

    vueCount += 1
    const parsed = parseSfc(source, { filename: file })
    for (const error of parsed.errors) addError(file, `SFC parse failed: ${String(error)}`)
    const descriptor = parsed.descriptor
    if (descriptor.script) scanScript(descriptor.script.content, file, descriptor.script.loc.start.offset)
    if (descriptor.scriptSetup) scanScript(descriptor.scriptSetup.content, file, descriptor.scriptSetup.loc.start.offset)

    const legacy = (policy.migration.legacyVuePaths ?? []).includes(file)
    if (legacy) continue
    if (file.startsWith('src/components/') && !approvedComponents.has(file)) {
      addError(file, 'local UI component is not approved in ui-policy.json')
    }
    if (descriptor.styles.length > 0 && !(policy.styles.allowedSfcStyleBlocks ?? []).includes(file)) {
      addError(file, 'SFC <style> blocks are forbidden; use the single approved project CSS entry')
    }
    if (descriptor.template) scanTemplate(descriptor.template.content, file)
  }

  const cssFiles = collectFiles(path.join(root, 'src'), ['.css'])
  for (const absoluteFile of cssFiles) {
    const file = relative(absoluteFile)
    if ((policy.migration.legacyCssPaths ?? []).includes(file)) continue
    if (!(policy.styles.allowedProjectCss ?? []).includes(file)) {
      addError(file, 'project CSS file is not the single policy-approved style entry')
      continue
    }
    const source = fs.readFileSync(absoluteFile, 'utf8')
    if (policy.styles.hardcodedColorsAllowed === false && /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i.test(source)) {
      addError(file, 'hardcoded colors are forbidden; use Bootstrap/AdminLTE variables')
    }
  }

  for (const component of policy.localComponents.approved ?? []) {
    const target = path.join(root, component.path)
    if (!fs.existsSync(target)) {
      addError('ui-policy.json', `approved local component path does not exist: ${component.path}`)
      continue
    }
    const actualCallers = [...importGraph.entries()]
      .filter(([caller, imports]) => caller.endsWith('.vue') && imports.has(component.path))
      .map(([caller]) => caller)
      .sort()
    const declaredCallers = [...(component.callers ?? [])].sort()
    for (const caller of declaredCallers) {
      if (!fs.existsSync(path.join(root, caller))) addError('ui-policy.json', `declared caller does not exist: ${caller}`)
      else if (!actualCallers.includes(caller)) addError('ui-policy.json', `${caller} no longer imports approved component ${component.name}`)
    }
    for (const caller of actualCallers) {
      if (!declaredCallers.includes(caller)) addError('ui-policy.json', `${caller} uses ${component.name} but is missing from its approved callers`)
    }
  }

  if (migrationPaths.length > 0) warnings.push(`${new Set(migrationPaths).size} temporary migration path exceptions remain`)
  return { errors, warnings, vueCount, scriptCount: sourceFiles.length - vueCount }
}

function parseArguments(argv) {
  let root = process.cwd()
  let policyPath
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--root' && argv[index + 1]) root = path.resolve(argv[++index])
    else if (argv[index] === '--policy' && argv[index + 1]) policyPath = path.resolve(argv[++index])
  }
  return { root, policyPath: policyPath ?? path.join(root, 'ui-policy.json') }
}

const isCli = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (isCli) {
  try {
    const { root, policyPath } = parseArguments(process.argv.slice(2))
    const result = checkWorkspace(root, policyPath)
    if (result.errors.length > 0) {
      console.error(`UI policy check failed with ${result.errors.length} error(s):`)
      for (const error of result.errors) console.error(`- ${error}`)
      process.exitCode = 1
    } else {
      console.log(`UI policy check passed (${result.vueCount} Vue files, ${result.scriptCount} script files).`)
      for (const warning of result.warnings) console.log(`Migration: ${warning}.`)
    }
  } catch (error) {
    console.error(`UI policy check could not run: ${error instanceof Error ? error.stack ?? error.message : String(error)}`)
    process.exitCode = 1
  }
}

export { checkWorkspace }
