import JSZip from 'jszip'
import type { FileEntry } from '../api/types'

export function downloadFile(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function downloadZip(files: FileEntry[]) {
  const zip = new JSZip()
  for (const f of files) {
    if (f.status === 'done' && f.result) {
      const name = f.file.name.replace(/\.(txt|json)$/i, '_anonymized.$1')
      zip.file(name, f.result.anonymized_text)
    }
  }
  const blob = await zip.generateAsync({ type: 'blob' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'anonymized_files.zip'
  a.click()
  URL.revokeObjectURL(url)
}
