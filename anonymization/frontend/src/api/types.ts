export interface Replacement {
  original: string
  placeholder: string
  category: string
  start: number
  end: number
}

export interface AnonymizeResponse {
  anonymized_text: string
  original_text: string
  replacements: Replacement[]
  stats: Record<string, number>
}

export interface AnonymizeConfig {
  categories?: string[]
  custom_brand_terms?: string[]
  placeholder_style?: 'numbered' | 'generic'
}

export type FileStatus = 'pending' | 'processing' | 'done' | 'error'

export interface FileEntry {
  file: File
  status: FileStatus
  error?: string
  result?: AnonymizeResponse
}
