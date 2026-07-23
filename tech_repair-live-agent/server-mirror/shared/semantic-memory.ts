/**
 * FAKE SHIM — Semantic Memory (mem0)
 * ==================================
 * The production module wraps mem0ai/oss (vector memory service). In the
 * simulation there is no mem0 backend, so this shim keeps the exact public
 * surface (`SemanticMemory`, `getSemanticMemory`, `_resetSemanticMemory`)
 * as no-ops: `addFacts` records facts in-memory for harness inspection,
 * `getContext` returns "" ("no facts found" — a valid production outcome),
 * and nothing ever throws. Everything else about the agent is untouched.
 */

import type { SupabaseClient } from "@supabase/supabase-js";

interface StoredFact {
    userId: string;
    fact: string;
    channel: "voice" | "whatsapp";
    runId?: string;
    at: string;
}

export class SemanticMemory {
    /** Facts recorded during the simulation — inspectable by the harness. */
    readonly recordedFacts: StoredFact[] = [];

    async addFacts(
        rawPhone: string,
        facts: string[],
        channel: "voice" | "whatsapp",
        runId?: string,
    ): Promise<void> {
        const at = new Date().toISOString();
        for (const fact of facts) {
            this.recordedFacts.push({ userId: rawPhone, fact, channel, runId, at });
        }
    }

    async getContext(
        _rawPhone: string,
        _query: string,
        _logContext?: {
            supabase?: SupabaseClient;
            callId?: string;
            conversationId?: string;
        },
    ): Promise<string> {
        // "" is the production behavior for "no facts found" — never throws.
        return "";
    }

    async deleteAll(_rawPhone: string): Promise<void> {
        // no-op
    }
}

let _instance: SemanticMemory | null = null;

export function getSemanticMemory(): SemanticMemory {
    if (!_instance) _instance = new SemanticMemory();
    return _instance;
}

export function _resetSemanticMemory(): void {
    _instance = null;
}
