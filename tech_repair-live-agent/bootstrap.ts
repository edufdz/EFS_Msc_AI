/**
 * Simulation Bootstrap
 * ====================
 * Plays the role of pulpoo-final's App layer: injects the (fake) Supabase
 * client and app id into the copied Core code, and pins the environment so
 * the agent runs fully offline except for LLM calls.
 *
 * The copied agent code is NEVER aware it's running against a fake DB —
 * it calls getSupabaseClient() exactly as in production.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { setSupabaseClient, setAppId } from "@/shared/supabase";
import { createFakeDb, createFakeSupabaseClient, type FakeSupabaseClient } from "./fake-db/fake-supabase";
import { buildSeedTables } from "./fake-db/seed";

let _client: FakeSupabaseClient | null = null;

export function bootstrapFakeEnvironment(): FakeSupabaseClient {
    if (_client) return _client;

    // --- Environment pinning (before getWhatsAppConfig() is first called) ---
    // Required-but-unused config values get fake placeholders; anything that
    // would open a real network path to TechRepair/Pulpoo infra is neutralized.
    process.env.SUPABASE_URL ??= "http://fake-supabase.simulation.local";
    process.env.SUPABASE_SERVICE_ROLE_KEY ??= "fake-service-role-key";
    // Force the LangGraph in-memory checkpointer (never Postgres).
    delete process.env.POSTGRES_CONNECTION_STRING;
    delete process.env.DATABASE_URL;
    // Push-bridge target: unroutable localhost port → instant refusal,
    // caught by the bridge's own fire-and-forget error handling.
    process.env.PULPOO_API_URL = "http://127.0.0.1:9";
    // GSPN credentials must stay empty — no call path exists in the copied
    // closure, but belt-and-braces.
    process.env.GSPN_BASE_URL = "";
    process.env.GSPN_TOKEN = "";

    if (!process.env.ANTHROPIC_API_KEY) {
        throw new Error(
            "ANTHROPIC_API_KEY is required (the agent's LLM calls are real; only the data layer is fake). Add it to tech_repair-live-agent/.env",
        );
    }
    if (!process.env.OPENAI_API_KEY) {
        // Config schema requires it (escalation verifier + provider fallback).
        console.warn("[bootstrap] OPENAI_API_KEY missing — using placeholder; escalation verification LLM calls will fail-safe.");
        process.env.OPENAI_API_KEY = "sk-fake-placeholder";
    }

    // --- Fake DB + injection (mirrors App bootstrap in pulpoo-final) ---
    const db = createFakeDb(buildSeedTables());
    _client = createFakeSupabaseClient(db);
    setSupabaseClient(_client as unknown as SupabaseClient);
    setAppId("fake-tech_repair-simulation");

    console.info("[bootstrap] Fake Supabase injected — tables:", [...db.tables.keys()].join(", "));
    return _client;
}

/** Reset the whole simulation state (fresh DB, fresh injection). */
export function resetFakeEnvironment(): FakeSupabaseClient {
    _client = null;
    return bootstrapFakeEnvironment();
}
