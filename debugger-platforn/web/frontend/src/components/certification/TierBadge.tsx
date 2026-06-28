import type { CertificationTier } from '../../api/types'

const TIER_CONFIG: Record<CertificationTier, {
  label: string
  primary: string
  secondary: string
  accent: string
  glow: string
}> = {
  platinum: {
    label: 'PLATINUM',
    primary: '#3B82F6',
    secondary: '#1D4ED8',
    accent: '#93C5FD',
    glow: 'rgba(59, 130, 246, 0.3)',
  },
  gold: {
    label: 'GOLD',
    primary: '#F59E0B',
    secondary: '#D97706',
    accent: '#FCD34D',
    glow: 'rgba(245, 158, 11, 0.3)',
  },
  silver: {
    label: 'SILVER',
    primary: '#9CA3AF',
    secondary: '#6B7280',
    accent: '#D1D5DB',
    glow: 'rgba(156, 163, 175, 0.3)',
  },
  not_certified: {
    label: 'NOT CERTIFIED',
    primary: '#EF4444',
    secondary: '#DC2626',
    accent: '#FCA5A5',
    glow: 'rgba(239, 68, 68, 0.2)',
  },
}

interface TierBadgeProps {
  tier: CertificationTier
  score: number
  size?: number
  animated?: boolean
}

export default function TierBadge({ tier, score, size = 180, animated = true }: TierBadgeProps) {
  const config = TIER_CONFIG[tier]
  const center = size / 2
  const outerR = size / 2 - 4
  const innerR = outerR * 0.62
  const scoreR = outerR * 0.78

  // Points for outer seal shape (zigzag border)
  const sealPoints = (count: number, rOuter: number, rInner: number) => {
    const pts: string[] = []
    for (let i = 0; i < count; i++) {
      const angle = (i * 2 * Math.PI) / count - Math.PI / 2
      const r = i % 2 === 0 ? rOuter : rInner
      pts.push(`${center + r * Math.cos(angle)},${center + r * Math.sin(angle)}`)
    }
    return pts.join(' ')
  }

  // Score arc
  const scoreAngle = (score / 100) * 360
  const describeArc = (r: number, startAngle: number, endAngle: number) => {
    const start = polarToCartesian(center, center, r, endAngle)
    const end = polarToCartesian(center, center, r, startAngle)
    const largeArc = endAngle - startAngle > 180 ? 1 : 0
    return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`
  }

  const polarToCartesian = (cx: number, cy: number, r: number, angleDeg: number) => {
    const rad = ((angleDeg - 90) * Math.PI) / 180
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
  }

  const animClass = animated ? 'animate-badge-reveal' : ''

  return (
    <div className={`relative inline-flex items-center justify-center ${animClass}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs>
          <linearGradient id={`grad-${tier}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={config.primary} />
            <stop offset="100%" stopColor={config.secondary} />
          </linearGradient>
          <filter id={`glow-${tier}`}>
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feFlood floodColor={config.glow} result="color" />
            <feComposite in="color" in2="blur" operator="in" result="shadow" />
            <feMerge>
              <feMergeNode in="shadow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {animated && (
            <style>{`
              @keyframes badge-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
              @keyframes badge-reveal {
                0% { opacity: 0; transform: scale(0.5); }
                60% { opacity: 1; transform: scale(1.08); }
                100% { transform: scale(1); }
              }
              .animate-badge-reveal { animation: badge-reveal 0.8s cubic-bezier(0.34, 1.56, 0.64, 1) forwards; }
              .seal-rotate { animation: badge-spin 60s linear infinite; transform-origin: ${center}px ${center}px; }
            `}</style>
          )}
        </defs>

        {/* Outer seal shape */}
        <polygon
          points={sealPoints(tier === 'platinum' ? 32 : tier === 'gold' ? 24 : 20, outerR, outerR * 0.88)}
          fill={`url(#grad-${tier})`}
          filter={`url(#glow-${tier})`}
          className={animated ? 'seal-rotate' : ''}
          opacity={0.15}
        />

        {/* Outer ring */}
        <circle cx={center} cy={center} r={outerR * 0.82} fill="none" stroke={config.primary} strokeWidth={2} opacity={0.3} />

        {/* Score arc track */}
        <circle cx={center} cy={center} r={scoreR} fill="none" stroke={config.accent} strokeWidth={4} opacity={0.2} />

        {/* Score arc fill */}
        {scoreAngle > 0 && (
          <path
            d={describeArc(scoreR, 0, Math.min(scoreAngle, 359.9))}
            fill="none"
            stroke={config.primary}
            strokeWidth={4}
            strokeLinecap="round"
          />
        )}

        {/* Inner circle background */}
        <circle cx={center} cy={center} r={innerR} fill="white" />
        <circle cx={center} cy={center} r={innerR} fill={config.primary} opacity={0.04} />
        <circle cx={center} cy={center} r={innerR} fill="none" stroke={config.primary} strokeWidth={1.5} opacity={0.2} />

        {/* Score text */}
        <text x={center} y={center - 6} textAnchor="middle" dominantBaseline="middle"
          fontSize={size * 0.2} fontWeight="700" fill={config.secondary} fontFamily="Inter, system-ui, sans-serif">
          {score.toFixed(1)}
        </text>

        {/* Label */}
        <text x={center} y={center + size * 0.12} textAnchor="middle" dominantBaseline="middle"
          fontSize={size * 0.065} fontWeight="600" fill={config.primary} fontFamily="Inter, system-ui, sans-serif"
          letterSpacing="2">
          {config.label}
        </text>
      </svg>
    </div>
  )
}
