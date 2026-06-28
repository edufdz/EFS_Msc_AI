import { useRef } from 'react'
import type { CertificationReport } from '../../api/types'
import TierBadge from './TierBadge'

interface PrintableCertificateProps {
  report: CertificationReport
  onClose: () => void
}

const TIER_LABELS: Record<string, { title: string; color: string }> = {
  platinum: { title: 'Platinum Certified', color: '#3B82F6' },
  gold: { title: 'Gold Certified', color: '#D97706' },
  silver: { title: 'Silver Certified', color: '#6B7280' },
  not_certified: { title: 'Assessment Complete', color: '#EF4444' },
}

export default function PrintableCertificate({ report, onClose }: PrintableCertificateProps) {
  const certRef = useRef<HTMLDivElement>(null)

  const tierInfo = TIER_LABELS[report.tier] || TIER_LABELS.not_certified
  const issuedDate = report.issued_at ? new Date(report.issued_at).toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric'
  }) : 'N/A'
  const expiresDate = report.expires_at ? new Date(report.expires_at).toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric'
  }) : 'N/A'

  const handlePrint = () => window.print()

  const handleExportPNG = async () => {
    if (!certRef.current) return
    try {
      const html2canvas = (await import('html2canvas')).default
      const canvas = await html2canvas(certRef.current, {
        scale: 2,
        backgroundColor: '#FFFFFF',
        useCORS: true,
      })
      const link = document.createElement('a')
      link.download = `plavio-cert-${report.certification_id}.png`
      link.href = canvas.toDataURL('image/png')
      link.click()
    } catch (err) {
      console.error('Export failed:', err)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4 overflow-auto print:bg-white print:p-0">
      {/* Action bar - hidden when printing */}
      <div className="fixed top-4 right-4 flex gap-2 print:hidden z-50">
        <button onClick={handleExportPNG}
          className="px-4 py-2 bg-accent text-white rounded-lg text-sm font-medium hover:bg-accent/90 shadow-lg">
          Export PNG
        </button>
        <button onClick={handlePrint}
          className="px-4 py-2 bg-white text-pearl border border-border rounded-lg text-sm font-medium hover:bg-bg-card shadow-lg">
          Print / PDF
        </button>
        <button onClick={onClose}
          className="px-4 py-2 bg-white text-text-dim border border-border rounded-lg text-sm font-medium hover:bg-bg-card shadow-lg">
          Close
        </button>
      </div>

      {/* Certificate document */}
      <div ref={certRef}
        className="bg-white w-[800px] min-h-[1060px] relative shadow-2xl print:shadow-none print:w-full"
        style={{ fontFamily: 'Inter, system-ui, sans-serif' }}
      >
        {/* Ornamental border */}
        <div className="absolute inset-3 border-2 rounded-sm" style={{ borderColor: tierInfo.color }} />
        <div className="absolute inset-5 border rounded-sm" style={{ borderColor: `${tierInfo.color}40` }} />

        {/* Corner ornaments */}
        {[['top-6 left-6', '0'], ['top-6 right-6', '90'], ['bottom-6 left-6', '270'], ['bottom-6 right-6', '180']].map(([pos, rot], i) => (
          <svg key={i} className={`absolute ${pos} w-8 h-8`} viewBox="0 0 32 32" style={{ transform: `rotate(${rot}deg)` }}>
            <path d="M0 0 L12 0 L12 2 L2 2 L2 12 L0 12 Z" fill={tierInfo.color} opacity={0.6} />
            <path d="M0 0 L6 0 L6 1 L1 1 L1 6 L0 6 Z" fill={tierInfo.color} />
          </svg>
        ))}

        <div className="px-16 py-12 flex flex-col items-center text-center min-h-[1060px]">
          {/* Header */}
          <div className="mb-2">
            <div className="text-sm tracking-[0.3em] uppercase text-text-muted font-medium">Plavio Agent Debugger</div>
          </div>

          <div className="w-32 border-t my-4" style={{ borderColor: tierInfo.color }} />

          <h1 className="text-3xl font-light tracking-wide text-pearl mb-1">
            Certificate of
          </h1>
          <h2 className="text-4xl font-bold tracking-wide mb-6" style={{ color: tierInfo.color }}>
            {tierInfo.title}
          </h2>

          <div className="text-sm text-text-muted mb-6 tracking-wider uppercase">This certifies that the agent</div>

          {/* Agent name */}
          <div className="text-3xl font-bold text-pearl mb-1 border-b-2 pb-2 px-8" style={{ borderColor: `${tierInfo.color}60` }}>
            {report.agent_name}
          </div>
          <div className="text-sm text-text-muted mt-2 mb-8">
            Framework: {report.agent_framework}
          </div>

          {/* Badge */}
          <div className="mb-8">
            <TierBadge tier={report.tier} score={report.overall_score} size={160} animated={false} />
          </div>

          {/* Category scores summary */}
          <div className="w-full max-w-md mb-8">
            <div className="text-xs tracking-[0.2em] uppercase text-text-muted mb-3">Category Performance</div>
            <div className="space-y-2">
              {report.category_scores.map((cs) => (
                <div key={cs.category} className="flex items-center justify-between text-sm">
                  <span className="text-text-dim">{cs.category}</span>
                  <div className="flex items-center gap-2">
                    <div className="w-24 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{
                        width: `${cs.score}%`,
                        backgroundColor: tierInfo.color
                      }} />
                    </div>
                    <span className="font-mono text-xs text-pearl w-8 text-right">{cs.score.toFixed(0)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Spacer to push footer down */}
          <div className="flex-1" />

          {/* Testing conditions */}
          <div className="text-xs text-text-muted mb-6 space-y-1">
            <div>Evaluated across {report.testing_conditions.total_simulations} simulations with {report.testing_conditions.persona_count} personas</div>
            <div>Confidence: {report.confidence.confidence_level.toFixed(1)}% | Margin of Error: +/- {report.confidence.margin_of_error.toFixed(1)}%</div>
          </div>

          {/* Divider */}
          <div className="w-48 border-t mb-6" style={{ borderColor: `${tierInfo.color}40` }} />

          {/* Dates and ID */}
          <div className="grid grid-cols-3 gap-8 text-center mb-6 w-full max-w-lg">
            <div>
              <div className="text-xs text-text-muted uppercase tracking-wider mb-1">Issued</div>
              <div className="text-sm font-medium text-pearl">{issuedDate}</div>
            </div>
            <div>
              <div className="text-xs text-text-muted uppercase tracking-wider mb-1">Valid Until</div>
              <div className="text-sm font-medium text-pearl">{expiresDate}</div>
            </div>
            <div>
              <div className="text-xs text-text-muted uppercase tracking-wider mb-1">Certificate ID</div>
              <div className="text-xs font-mono text-text-dim break-all">{report.certification_id}</div>
            </div>
          </div>

          {/* Watermark text */}
          <div className="text-[10px] text-text-muted tracking-wider">
            Verified by Plavio Agent Certification System
          </div>
        </div>
      </div>
    </div>
  )
}
