import type { PhaseDResult } from '../../api/types'
import TriageSummaryBar from './TriageSummaryBar'
import SeverityOverview from './SeverityOverview'
import RootCauseChart from './RootCauseChart'
import ImprovementProjection from './ImprovementProjection'
import PriorityClusterList from './PriorityClusterList'
import FixRoadmap from './FixRoadmap'
import ToolFailureHeatmap from './ToolFailureHeatmap'

interface DiagnosisDashboardProps {
  result: PhaseDResult
  sessionId: string
}

export default function DiagnosisDashboard({ result, sessionId }: DiagnosisDashboardProps) {
  if (result.total_failures === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-3">
        <div className="text-4xl">&#10003;</div>
        <p className="text-pearl font-medium">No failures to diagnose</p>
        <p className="text-sm text-text-muted">All tests passed — no diagnosis needed</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* KPI Cards */}
      <TriageSummaryBar result={result} />

      {/* Severity + Root Cause side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SeverityOverview result={result} />
        <RootCauseChart result={result} />
      </div>

      {/* Improvement Projection */}
      <ImprovementProjection result={result} />

      {/* Priority Clusters */}
      <PriorityClusterList
        clusters={result.clusters}
        fixProposals={result.fix_proposals}
        priorityRanking={result.priority_ranking}
        sessionId={sessionId}
      />

      {/* Fix Roadmap */}
      <FixRoadmap
        fixProposals={result.fix_proposals}
        clusters={result.clusters}
      />

      {/* Tool Failure Heatmap */}
      <ToolFailureHeatmap clusters={result.clusters} />
    </div>
  )
}
