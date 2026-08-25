#!/usr/bin/env node

import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

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

function sourceLine(source, offset) {
  return source.slice(0, offset).split(/\r?\n/).length
}

function packageName(specifier) {
  if (specifier.startsWith('@')) return specifier.split('/').slice(0, 2).join('/')
  return specifier.split('/')[0]
}

function hasHardcodedColor(source) {
  return /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i.test(source)
}

function checkWorkspace(root, policyPath) {
  const policy = readJson(policyPath)
  const packageJson = readJson(path.join(root, 'package.json'))
  const errors = []
  const dependencies = { ...(packageJson.devDependencies ?? {}), ...(packageJson.dependencies ?? {}) }
  const forbiddenDependencies = new Set(policy.dependencies.forbidden ?? [])
  const controlledImports = policy.adminLteVue.controlledImports ?? {}
  const globalCssPaths = new Set(policy.styles.globalCssPaths ?? [])
  const requiredCssOwners = new Map([
    ['@adminlte/vue/css', new Set(policy.adminLteVue.cssImportPaths ?? [])],
    ['bootstrap-icons/font/bootstrap-icons.css', new Set(policy.icons.cssImportPaths ?? [])],
  ])
  const observedCssImports = new Set()
  const observedGlobalCssImports = new Set()
  const relative = (file) => normalizePath(path.relative(root, file))
  const addError = (file, message, line) => {
    errors.push(`${file}${line ? `:${line}` : ''} ${message}`)
  }

  for (const [name, expected] of Object.entries(policy.dependencies.requiredExact ?? {})) {
    const actual = dependencies[name]
    if (actual !== expected) addError('package.json', `requires exact ${name}@${expected}; found ${actual ?? 'missing'}`)
  }
  for (const name of forbiddenDependencies) {
    if (name in dependencies) addError('package.json', `forbidden dependency "${name}" is installed directly`)
  }

  function scanScript(source, file, sourceOffset = 0) {
    const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    for (const statement of sourceFile.statements) {
      if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue
      const moduleName = statement.moduleSpecifier.text
      const line = sourceLine(source, statement.getStart(sourceFile)) + sourceLine(source, sourceOffset) - 1

      if (moduleName.endsWith('.css')) {
        const target = moduleName.startsWith('@/')
          ? normalizePath(path.join('src', moduleName.slice(2)))
          : moduleName.startsWith('.')
            ? normalizePath(path.relative(root, path.resolve(root, path.dirname(file), moduleName)))
            : ''
        if (globalCssPaths.has(target)) observedGlobalCssImports.add(target)
      }

      if (forbiddenDependencies.has(moduleName) || forbiddenDependencies.has(packageName(moduleName))) {
        addError(file, `importing forbidden dependency "${moduleName}"`, line)
      }
      if (moduleName === '@adminlte/vue/css') {
        if (!(policy.adminLteVue.cssImportPaths ?? []).includes(file)) {
          addError(file, '@adminlte/vue/css may only be imported by the shared CSS entry owner', line)
        } else {
          observedCssImports.add(`${moduleName}:${file}`)
        }
        continue
      }
      if (moduleName.startsWith('@adminlte/vue/') && moduleName !== '@adminlte/vue') {
        addError(file, `unsupported AdminLTE subpath import "${moduleName}"; use named @adminlte/vue imports`, line)
        continue
      }
      if (moduleName === 'bootstrap-icons/font/bootstrap-icons.css') {
        if (!(policy.icons.cssImportPaths ?? []).includes(file)) {
          addError(file, 'Bootstrap Icons CSS may only be imported by the shared CSS entry owner', line)
        } else {
          observedCssImports.add(`${moduleName}:${file}`)
        }
        continue
      }
      if (moduleName !== '@adminlte/vue') continue

      const clause = statement.importClause
      if (!clause) continue
      if (clause.name || (clause.namedBindings && ts.isNamespaceImport(clause.namedBindings))) {
        addError(file, 'AdminLTE must use named imports instead of default, namespace, or global registration', line)
      }
      if (!clause.namedBindings || !ts.isNamedImports(clause.namedBindings)) continue
      for (const specifier of clause.namedBindings.elements) {
        const name = specifier.propertyName?.text ?? specifier.name.text
        const owners = controlledImports[name]
        if (owners && !owners.includes(file)) {
          addError(file, `AdminLTE shell primitive "${name}" is owned by ${owners.join(', ')}`, line)
        }
      }
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
    const inlineAllowed = (policy.styles.inlineStylePaths ?? []).includes(file)
    function visit(node) {
      if (node.type === NodeTypes.ELEMENT) {
        for (const prop of node.props) {
          const staticStyle = prop.type === NodeTypes.ATTRIBUTE && prop.name === 'style'
          const boundStyle = prop.type === NodeTypes.DIRECTIVE
            && prop.name === 'bind'
            && prop.arg?.type === NodeTypes.SIMPLE_EXPRESSION
            && prop.arg.content === 'style'
          if (!inlineAllowed && (staticStyle || boundStyle)) {
            addError(file, 'inline styles are forbidden; use shared CSS or a scoped component style', prop.loc.start.line)
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
    if (descriptor.template) scanTemplate(descriptor.template.content, file)
    for (const style of descriptor.styles) {
      if (policy.styles.allowScopedSfcStyles !== true || !style.scoped) {
        addError(file, 'SFC styles must be scoped; reusable global patterns belong in the shared CSS entry')
      }
      if (policy.styles.hardcodedColorsAllowed === false && hasHardcodedColor(style.content)) {
        addError(file, 'hardcoded colors are forbidden; use Bootstrap/AdminLTE theme variables')
      }
    }
  }

  for (const [moduleName, owners] of requiredCssOwners) {
    for (const owner of owners) {
      if (!observedCssImports.has(`${moduleName}:${owner}`)) {
        addError(owner, `must import required shared stylesheet "${moduleName}"`)
      }
    }
  }

  for (const stylesheet of globalCssPaths) {
    if (!fs.existsSync(path.join(root, stylesheet))) {
      addError(stylesheet, 'declared shared project stylesheet does not exist')
    } else if (!observedGlobalCssImports.has(stylesheet)) {
      addError(stylesheet, 'shared project stylesheet must be imported by a source entry')
    }
  }

  for (const absoluteFile of collectFiles(path.join(root, 'src'), ['.css'])) {
    const file = relative(absoluteFile)
    if (!globalCssPaths.has(file)) {
      addError(file, 'global project CSS must use the shared policy-owned entry')
      continue
    }
    const source = fs.readFileSync(absoluteFile, 'utf8')
    if (policy.styles.hardcodedColorsAllowed === false && hasHardcodedColor(source)) {
      addError(file, 'hardcoded colors are forbidden; use Bootstrap/AdminLTE theme variables')
    }
  }

  return { errors, vueCount, scriptCount: sourceFiles.length - vueCount }
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

try {
  const { root, policyPath } = parseArguments(process.argv.slice(2))
  const result = checkWorkspace(root, policyPath)
  if (result.errors.length > 0) {
    console.error(`UI policy check failed with ${result.errors.length} error(s):`)
    for (const error of result.errors) console.error(`- ${error}`)
    process.exitCode = 1
  } else {
    console.log(`UI policy check passed (${result.vueCount} Vue files, ${result.scriptCount} script files).`)
  }
} catch (error) {
  console.error(`UI policy check could not run: ${error instanceof Error ? error.stack ?? error.message : String(error)}`)
  process.exitCode = 1
}
