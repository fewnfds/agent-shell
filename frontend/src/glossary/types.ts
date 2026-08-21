export type GlossaryScope = 'ai-agent-concept' | 'project-technology'

export interface GlossarySource {
  label: string
  url: string
}

export interface GlossaryEntry {
  key: string
  english: string
  variants: string[]
  zh: string
  descriptionZh: string
  descriptionEn: string
  sources: GlossarySource[]
  scope: GlossaryScope
}
