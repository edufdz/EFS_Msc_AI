/**
 * FAKE SHIM — Survey Orchestrator
 * ===============================
 * The production orchestrator intercepts WhatsApp turns for customers with
 * an active NPS survey (deep subtree: survey.repository, conductor, NPS
 * math, extractors). The fake customer has no active survey, so this shim
 * keeps the exact call contract used by agent.ts and always returns null —
 * "no active survey, continue with the normal LangGraph flow", which is a
 * first-class production outcome.
 */

export interface SurveyHandleArgs {
    phone: string;
    conversationId: string | null;
    message: string;
}

export interface SurveyHandleResult {
    response_text: string;
    completed: boolean;
    metadata: {
        survey_id: string;
        turn_kind: string;
        survey_status_after: string;
    };
}

export interface SurveyOrchestrator {
    handle(args: SurveyHandleArgs): Promise<SurveyHandleResult | null>;
}

const _orchestrator: SurveyOrchestrator = {
    async handle(_args: SurveyHandleArgs): Promise<SurveyHandleResult | null> {
        return null; // no active survey for the fake customer
    },
};

export function getSurveyOrchestrator(): SurveyOrchestrator {
    return _orchestrator;
}
