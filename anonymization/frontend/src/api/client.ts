import type { AnonymizeConfig, AnonymizeResponse } from './types'

export async function previewFile(
  file: File,
  config?: AnonymizeConfig,
): Promise<AnonymizeResponse> {
  const form = new FormData()
  form.append('file', file)
  if (config) form.append('config', JSON.stringify(config))
  const res = await fetch('/api/anonymize/preview', { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function anonymizeFile(
  file: File,
  config?: AnonymizeConfig,
): Promise<{ anonymized_text: string }> {
  const form = new FormData()
  form.append('file', file)
  if (config) form.append('config', JSON.stringify(config))
  const res = await fetch('/api/anonymize', { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
