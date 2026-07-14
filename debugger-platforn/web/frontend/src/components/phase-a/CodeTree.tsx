import { useState } from 'react'
import type { CodeTree as CodeTreeData, CodeTreeNode } from '../../api/types'

/**
 * Hierarchical view of the analyzed agent's codebase:
 * directories → files → classes → functions/methods, annotated with the
 * tools, prompts, risks, and entry points Phase A discovered at each node.
 */
export default function CodeTree({ codeTree }: { codeTree: CodeTreeData }) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <h4 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
          Code Structure
        </h4>
        <span className="text-[11px] text-text-muted font-mono">
          {codeTree.total_files} files · {codeTree.total_classes} classes ·{' '}
          {codeTree.total_functions} functions
        </span>
      </div>
      <div className="bg-bg-card border border-border rounded-lg p-2 max-h-[520px] overflow-y-auto">
        <TreeNode node={codeTree.tree} depth={0} />
      </div>
    </div>
  )
}

const severityColor: Record<string, string> = {
  critical: 'bg-red-500',
  high: 'bg-orange-500',
  medium: 'bg-amber-400',
  low: 'bg-emerald-500',
}

function TreeNode({ node, depth }: { node: CodeTreeNode; depth: number }) {
  // Directories start expanded near the root; files/classes start collapsed.
  const [open, setOpen] = useState(node.type === 'directory' && depth < 2)
  const children = node.children ?? []
  const expandable = children.length > 0

  return (
    <div>
      <div
        className={`flex items-center gap-1.5 px-1.5 py-[3px] rounded hover:bg-white/5 ${
          expandable ? 'cursor-pointer select-none' : ''
        }`}
        style={{ paddingLeft: `${depth * 16 + 6}px` }}
        onClick={() => expandable && setOpen(!open)}
      >
        {/* Chevron */}
        <span className="w-3 text-text-muted text-[10px] shrink-0">
          {expandable ? (open ? '▾' : '▸') : ''}
        </span>

        <NodeIcon node={node} />

        {/* Name + signature */}
        <span
          className={`text-[13px] font-mono truncate ${
            node.type === 'directory'
              ? 'text-pearl font-semibold'
              : node.type === 'file'
                ? 'text-smoke'
                : 'text-text-muted'
          }`}
        >
          {node.name}
          {(node.type === 'function' || node.type === 'method') && (
            <span className="text-text-muted/70">({(node.params ?? []).join(', ')})</span>
          )}
          {node.type === 'class' && node.bases && node.bases.length > 0 && (
            <span className="text-text-muted/70"> : {node.bases.join(', ')}</span>
          )}
        </span>

        <NodeBadges node={node} />
      </div>

      {open &&
        children.map((child, i) => (
          <TreeNode key={`${child.type}-${child.name}-${i}`} node={child} depth={depth + 1} />
        ))}
    </div>
  )
}

function NodeIcon({ node }: { node: CodeTreeNode }) {
  const cls = 'w-3.5 text-[11px] shrink-0 text-center'
  switch (node.type) {
    case 'directory':
      return <span className={`${cls} text-amber-300/80`}>▣</span>
    case 'file':
      return <span className={`${cls} text-sky-300/80`}>≡</span>
    case 'class':
      return <span className={`${cls} text-purple-300/80 font-bold`}>C</span>
    case 'method':
      return <span className={`${cls} text-teal-300/80 font-bold`}>m</span>
    default:
      return <span className={`${cls} text-teal-300/80 font-bold`}>ƒ</span>
  }
}

function NodeBadges({ node }: { node: CodeTreeNode }) {
  const c = node.counts
  return (
    <span className="flex items-center gap-1.5 ml-auto shrink-0 pr-1">
      {node.is_async && <Chip label="async" className="text-sky-300 border-sky-300/30" />}
      {node.is_entry_point && (
        <Chip label="entry" className="text-emerald-300 border-emerald-300/30" />
      )}
      {node.implements_tool && (
        <Chip label={`⚙ ${node.implements_tool}`} className="text-indigo-300 border-indigo-300/30" />
      )}
      {node.type === 'file' && node.tools && node.tools.length > 0 && (
        <Chip
          label={`⚙ ${node.tools.length} tool${node.tools.length > 1 ? 's' : ''}`}
          className="text-indigo-300 border-indigo-300/30"
          title={node.tools.map((t) => t.name).join(', ')}
        />
      )}
      {node.prompts && node.prompts.length > 0 && (
        <Chip
          label={`✎ ${node.prompts.length}`}
          className="text-amber-300 border-amber-300/30"
          title={node.prompts.join(', ')}
        />
      )}
      {node.type === 'directory' && c && (
        <span className="text-[10px] text-text-muted font-mono tabular-nums">
          {c.files}f{c.tools > 0 ? ` · ${c.tools}⚙` : ''}
        </span>
      )}
      {node.max_risk_severity && (
        <span
          className={`w-2 h-2 rounded-full ${severityColor[node.max_risk_severity] ?? 'bg-gray-400'}`}
          title={
            node.risks?.map((r) => `${r.severity}: ${r.description}`).join('\n') ??
            `max risk: ${node.max_risk_severity}`
          }
        />
      )}
    </span>
  )
}

function Chip({
  label,
  className,
  title,
}: {
  label: string
  className: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={`text-[10px] px-1.5 py-px rounded border bg-white/5 whitespace-nowrap ${className}`}
    >
      {label}
    </span>
  )
}
