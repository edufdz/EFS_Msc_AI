/**
 * Lane-selector — public surface barrel.
 *
 * Three routers, one shared decision-logic helper:
 *   * resolveServiceTypeForConversation — WhatsApp inbound
 *   * resolveServiceTypeForVoice        — voice inbound
 *   * routeStatusChangeWrite            — GSPN sync writes
 *
 * All three log to `agent_thoughts` (thought_type='lane_decision') so
 * misroute investigation is one query away.
 *
 * **Critical default rule:** none of these routers ever silently
 * collapse 'unknown' or 'ambiguous' to a definitive pipeline. The four-
 * value contract is the whole point of this module.
 *
 * See `/SERVICE_TYPE_CLASSIFICATION.md` for the source-of-truth for the
 * underlying `service_type` column the routers read from.
 */

export type { LaneDecision, ResolvedLane, LaneCandidateOrder } from "./types";
export { resolveServiceTypeForConversation } from "./conversation-router";
export { resolveServiceTypeForVoice } from "./voice-router";
export {
    routeStatusChangeWrite,
    routeStatusChangeBatch,
    type StatusChangeRow,
    type StatusChangeRowWithType,
    type SyncRouteResult,
    type SyncRouteBatchResult,
} from "./sync-router";

// Generic agent_thoughts logging primitives. Use logAgentThought for any
// thought_type; use the typed wrappers when the call site matches one of
// the established categories. NOT yet wired into the existing escalation
// or memory paths — those refactors land in their own tasks.
export {
    logAgentThought,
    logEscalationReason,
    logMemoryRetrieval,
} from "./internal";
