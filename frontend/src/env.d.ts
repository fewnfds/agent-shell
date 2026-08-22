/// <reference types="vite/client" />

declare module 'virtual:style-baseline' {
  type StyleClass = {
    name: string
    usageCount: number
    sources: string[]
    recipes: string[]
    status: 'registered' | 'external' | 'suspect'
    approved: boolean
  }

  export const styleBaseline: {
    classInventory: StyleClass[]
    summary: {
      classCount: number
      usedClassCount: number
      suspectClassCount: number
      componentCount: number
    }
  }
}
