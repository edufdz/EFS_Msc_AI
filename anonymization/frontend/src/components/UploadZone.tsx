import { useCallback, useRef, useState } from 'react'

interface Props {
  onFilesAdded: (files: File[]) => void
}

export default function UploadZone({ onFilesAdded }: Props) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFiles = useCallback(
    (fileList: FileList) => {
      const txtFiles = Array.from(fileList).filter((f) => {
        const name = f.name.toLowerCase()
        return name.endsWith('.txt') || name.endsWith('.json')
      })
      if (txtFiles.length > 0) onFilesAdded(txtFiles)
    },
    [onFilesAdded],
  )

  return (
    <div
      className={`border-2 border-dashed rounded-lg p-12 text-center cursor-pointer transition-colors ${
        dragging
          ? 'border-accent bg-blue-50'
          : 'border-border hover:border-accent-dim'
      }`}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        handleFiles(e.dataTransfer.files)
      }}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".txt,.json"
        className="hidden"
        onChange={(e) => {
          if (e.target.files) handleFiles(e.target.files)
          e.target.value = ''
        }}
      />
      <div className="text-text-muted text-lg mb-2">
        {dragging ? 'Drop files here' : 'Drag & drop TXT or JSON files here'}
      </div>
      <div className="text-text-muted text-sm">or click to browse</div>
    </div>
  )
}
