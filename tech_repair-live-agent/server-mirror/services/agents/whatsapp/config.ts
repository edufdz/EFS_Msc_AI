/**
 * WhatsApp Agent Configuration
 * ============================
 * Zod-validated environment configuration.
 */

import { z } from "zod/v4";

const WhatsAppConfigSchema = z.object({
    // OpenAI (kept for interaction grader, escalation verifier, unified extraction)
    openaiApiKey: z.string(),
    openaiModel: z.string().default("gpt-4o-mini"),
    openaiTemperature: z.coerce.number().default(0.3),

    // Anthropic (ROCKET multi-lane)
    anthropicApiKey: z.string(),
    lane1Model: z.string().default("claude-haiku-4-5-20251001"),
    lane2Model: z.string().default("claude-sonnet-4-5-20250929"),
    lane1MaxTokens: z.coerce.number().int().default(300),
    lane2MaxTokens: z.coerce.number().int().default(600),
    maxContextTurns: z.coerce.number().int().default(5),

    // Supabase
    supabaseUrl: z.string(),
    supabaseServiceRoleKey: z.string(),

    // PostgreSQL (for LangGraph checkpointer — optional, falls back to in-memory)
    postgresConnectionString: z.string().optional(),

    // TechRepair GSPN
    gspnBaseUrl: z.string().default(""),
    gspnToken: z.string().default(""),
    gspnAscCode: z.string().default(""),

    // Agent behavior
    maxResponseLength: z.coerce.number().int().default(450),
    maxToolRetries: z.coerce.number().int().default(2),
    escalationThreshold: z.coerce.number().int().default(3),
    batchDelayMs: z.coerce.number().int().default(3000),
    defaultLanguage: z.string().default("es-MX"),
    supportPhone: z.string().default("+525588974249"),
    intentTaxonomyVersion: z.enum(["v1", "v2"]).default("v2"),

    // Business info
    businessName: z.string().default("Centro de Servicio TechRepair Polanco"),
    businessHours: z.string().default("Lunes a Sábado 10:00-19:00"),
    businessAddress: z.string().default("Calz. Gral. Mariano Escobedo 476, Chapultepec Morales, Anzures, Miguel Hidalgo, 11590 Ciudad de México, CDMX"),
    businessEmail: z.string().default("logistica.d2d@gruposim-tech.com"),

    // Logging
    logLevel: z.string().default("INFO"),
});

export type WhatsAppConfig = z.infer<typeof WhatsAppConfigSchema>;

let _config: WhatsAppConfig | null = null;

/**
 * Load and validate WhatsApp agent configuration from environment.
 */
export function getWhatsAppConfig(): WhatsAppConfig {
    if (_config) return _config;

    _config = WhatsAppConfigSchema.parse({
        openaiApiKey: process.env.OPENAI_API_KEY,
        openaiModel: process.env.OPENAI_MODEL,
        openaiTemperature: process.env.OPENAI_TEMPERATURE,
        anthropicApiKey: process.env.ANTHROPIC_API_KEY,
        lane1Model: process.env.LANE1_MODEL,
        lane2Model: process.env.LANE2_MODEL,
        lane1MaxTokens: process.env.LANE1_MAX_TOKENS,
        lane2MaxTokens: process.env.LANE2_MAX_TOKENS,
        maxContextTurns: process.env.MAX_CONTEXT_TURNS,
        supabaseUrl: process.env.SUPABASE_URL,
        supabaseServiceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
        postgresConnectionString: process.env.POSTGRES_CONNECTION_STRING
            ?? process.env.DATABASE_URL,
        gspnBaseUrl: process.env.GSPN_BASE_URL,
        gspnToken: process.env.GSPN_TOKEN,
        gspnAscCode: process.env.GSPN_ASC_CODE,
        maxResponseLength: process.env.MAX_RESPONSE_LENGTH,
        maxToolRetries: process.env.MAX_TOOL_RETRIES,
        escalationThreshold: process.env.ESCALATION_THRESHOLD,
        defaultLanguage: process.env.DEFAULT_LANGUAGE,
        supportPhone: process.env.SUPPORT_PHONE,
        businessName: process.env.BUSINESS_NAME,
        businessHours: process.env.BUSINESS_HOURS,
        businessAddress: process.env.BUSINESS_ADDRESS,
        businessEmail: process.env.BUSINESS_EMAIL,
        intentTaxonomyVersion: process.env.INTENT_TAXONOMY_VERSION,
        logLevel: process.env.LOG_LEVEL,
    });

    return _config;
}

/**
 * Load WhatsApp config with DB overrides from agent_configurations table.
 * Falls back to env config if DB is unavailable.
 */
export async function getWhatsAppDynamicConfig(): Promise<WhatsAppConfig> {
    const envConfig = getWhatsAppConfig();

    try {
        const { loadAgentConfig } = await import("@/services/agents/shared/dynamic-config");
        const dbConfig = await loadAgentConfig("whatsapp");
        if (!dbConfig) return envConfig;

        const extraTaxonomy = dbConfig.extra_config?.intent_taxonomy_version;
        const intentTaxonomyVersion =
            extraTaxonomy === "v1" || extraTaxonomy === "v2"
                ? extraTaxonomy
                : envConfig.intentTaxonomyVersion;

        return {
            ...envConfig,
            openaiModel: dbConfig.llm_model || envConfig.openaiModel,
            openaiTemperature: dbConfig.llm_temperature ?? envConfig.openaiTemperature,
            maxResponseLength: dbConfig.max_response_length ?? envConfig.maxResponseLength,
            escalationThreshold: dbConfig.escalation_threshold ?? envConfig.escalationThreshold,
            batchDelayMs: dbConfig.batch_delay_ms ?? envConfig.batchDelayMs,
            intentTaxonomyVersion,
        };
    } catch {
        return envConfig;
    }
}

/** Reset cached config (for testing). */
export function _resetConfig(): void {
    _config = null;
}
