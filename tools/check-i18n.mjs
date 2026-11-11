// Check that every t('...') key exists in both i18n bundles, and vice versa.
import fs from 'node:fs'

import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const target = process.argv[2] ?? path.join(here, '..', 'desktop', 'plugin.js')
const src = fs.readFileSync(target, 'utf8')
const start = src.indexOf('const STRINGS = {')
const end = src.indexOf('// ── store', start)
const literal = src.slice(start, end).trim().replace(/;?$/, '')
const STRINGS = new Function(`${literal}; return STRINGS`)()

const used = new Set([...src.matchAll(/\bt\('([a-zA-Z_.]+)'/g)].map(m => m[1]))

const flatten = (obj, prefix = '') =>
  Object.entries(obj).flatMap(([key, value]) =>
    value && typeof value === 'object' ? flatten(value, `${prefix}${key}.`) : [`${prefix}${key}`]
  )

const en = new Set(flatten(STRINGS.en))
const ja = new Set(flatten(STRINGS.ja))

const report = (label, list) => {
  if (list.length) {
    console.log(`${label}: ${list.join(', ')}`)
    process.exitCode = 1
  }
}

report('missing in en', [...used].filter(k => !en.has(k)).sort())
report('missing in ja', [...used].filter(k => !ja.has(k)).sort())
report('en/ja differ', [...en].filter(k => !ja.has(k)).concat([...ja].filter(k => !en.has(k))).sort())
report('unused in en', [...en].filter(k => !used.has(k)).sort())
if (!process.exitCode) console.log(`i18n OK — ${used.size} keys used, ${en.size} defined in each bundle`)
