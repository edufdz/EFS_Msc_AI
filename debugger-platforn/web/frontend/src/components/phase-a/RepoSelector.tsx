import FileExplorer from '../shared/FileExplorer'

interface RepoSelectorProps {
  repoPath: string
  onPathChange: (path: string) => void
}

export default function RepoSelector({ repoPath, onPathChange }: RepoSelectorProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Agent Repository
      </h3>
      <FileExplorer selectedPath={repoPath} onSelect={onPathChange} />
    </div>
  )
}
