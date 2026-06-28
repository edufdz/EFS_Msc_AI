import { getCategoryColor } from '../utils/highlights'

interface Props {
  stats: Record<string, number> | null
}

export default function StatsBar({ stats }: Props) {
  if (!stats || Object.keys(stats).length === 0) return null

  return (
    <div className="flex flex-wrap gap-2">
      {Object.entries(stats).map(([category, count]) => (
        <span
          key={category}
          className={`${getCategoryColor(category)} text-text-primary text-xs font-medium px-2.5 py-1 rounded-full`}
        >
          {category}: {count}
        </span>
      ))}
    </div>
  )
}
