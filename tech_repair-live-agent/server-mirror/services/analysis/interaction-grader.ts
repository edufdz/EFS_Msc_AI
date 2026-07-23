/**
 * Interaction Grader — Hybrid Agent Performance Scoring
 * =====================================================
 * Grades every closed WhatsApp interaction using a two-step approach:
 *
 * 1. **Deterministic Scorer** — instant, no LLM — computes hard metrics from
 *    existing telemetry (message counts, response lengths, tool usage, memory hits).
 *
 * 2. **LLM Evaluator** (gpt-4o-mini) — receives deterministic signals + transcript,
 *    evaluates rule adherence, over-engineering, and qualitative quality.
 *
 * 3. **Composite** — merges both into a final scorecard stored in `interaction_grades`.
 */

import { z } from "zod";
import { getSupabaseClient } from "@/shared/supabase";
import { createTrackedLLM } from "@/shared/llm-tracker";
import { SUPPORT_SYSTEM_PROMPT } from "@/services/agents/whatsapp/prompts/support";
import { getWhatsAppConfig } from "@/services/agents/whatsapp/config";

// =============================================================================
// Types
// =============================================================================

export interface GradeInteractionParams {
    conversationId: string;
    phone: string;
    interactionId: string | null;
    transcript: string;
    sentimentScore: number;
    outcome: string;
}

export interface DeterministicSignals {
    message_count: number;
    agent_message_count: number;
    customer_message_count: number;
    avg_response_length: number;
    max_response_length: number;
    tool_calls_total: number;
    tool_calls_succeeded: number;
    tool_calls_failed: number;
    memory_searches: number;
    memory_hits: number;
    avg_memory_latency_ms: number;
    avg_response_time_ms: number;
    escalated: boolean;
    outcome: string;
    sentiment_score: number;
}

const QualitativeGradeSchema = z.object({
    rule_adherence: z.number().min(0).max(100).describe("Score 0-100 for how well the agent followed the 18 rules"),
    rule_explanation: z.string().describe("Brief explanation of rule compliance"),
    rule_violations: z.array(z.object({
        rule_number: z.number().describe("Rule number 1-18 that was violated"),
        description: z.string().describe("What the agent did wrong"),
    })).describe("List of specific rule violations found"),
    over_engineering_flags: z.array(z.object({
        type: z.enum([
            "unnecessary_tool_call",
            "verbose_response",
            "repeated_info",
            "unnecessary_disclaimer",
            "over_escalation",
        ]).describe("Category of over-engineering"),
        description: z.string().describe("What happened"),
        evidence: z.string().describe("Direct quote from the transcript"),
    })).describe("Instances where the agent over-engineered its response"),
    qualitative_notes: z.string().describe("Overall quality assessment"),
    strengths: z.array(z.string()).describe("Things the agent did well"),
    escalation_assessment: z.number().min(0).max(100).optional().describe("Score 0-100 for escalation appropriateness, only if escalated"),
    escalation_explanation: z.string().optional().describe("Why the escalation was or wasn't appropriate"),
});

type QualitativeGrade = z.infer<typeof QualitativeGradeSchema>;

// =============================================================================
// Step 1: Deterministic Scorer
// =============================================================================

async function computeDeterministicSignals(
    conversationId: string,
    sentimentScore: number,
    outcome: string,
): Promise<DeterministicSignals> {
    const sb = getSupabaseClient();
    if (!sb) throw new Error("No Supabase client available");

    // Fetch all data in parallel
    const [messagesRes, memoryRes, toolsRes, thoughtsRes] = await Promise.all([
        sb.from("whatsapp_messages")
            .select("direction, body, created_at")
            .eq("conversation_id", conversationId)
            .order("created_at", { ascending: true }),
        sb.from("memory_logs")
            .select("memory_count, latency_ms")
            .eq("conversation_id", conversationId),
        sb.from("tool_invocations")
            .select("success, execution_time_ms")
            .eq("conversation_id", conversationId),
        sb.from("thought_logs")
            .select("step_name, created_at")
            .eq("conversation_id", conversationId)
            .order("created_at", { ascending: true }),
    ]);

    const messages = messagesRes.data ?? [];
    const memoryLogs = memoryRes.data ?? [];
    const toolCalls = toolsRes.data ?? [];
    const thoughts = thoughtsRes.data ?? [];

    // Message metrics
    const agentMessages = messages.filter((m: { direction: string }) => m.direction === "outbound");
    const customerMessages = messages.filter((m: { direction: string }) => m.direction === "inbound");
    const agentLengths = agentMessages.map((m: { body: string | null }) => (m.body ?? "").length);
    const avgResponseLength = agentLengths.length > 0
        ? Math.round(agentLengths.reduce((a: number, b: number) => a + b, 0) / agentLengths.length)
        : 0;
    const maxResponseLength = agentLengths.length > 0 ? Math.max(...agentLengths) : 0;

    // Response time: avg time between customer msg → next agent msg
    const responseTimes: number[] = [];
    for (let i = 0; i < messages.length; i++) {
        const msg = messages[i] as { direction: string; created_at: string };
        if (msg.direction === "inbound") {
            const nextAgent = messages.slice(i + 1).find(
                (m: { direction: string }) => m.direction === "outbound"
            ) as { created_at: string } | undefined;
            if (nextAgent) {
                const diff = new Date(nextAgent.created_at).getTime() - new Date(msg.created_at).getTime();
                if (diff > 0) responseTimes.push(diff);
            }
        }
    }
    const avgResponseTime = responseTimes.length > 0
        ? Math.round(responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length)
        : 0;

    // Memory metrics
    const memorySearches = memoryLogs.length;
    const memoryHits = memoryLogs.filter((m: { memory_count: number }) => m.memory_count > 0).length;
    const memLatencies = memoryLogs
        .filter((m: { latency_ms: number | null }) => m.latency_ms != null)
        .map((m: { latency_ms: number }) => m.latency_ms);
    const avgMemoryLatency = memLatencies.length > 0
        ? Math.round(memLatencies.reduce((a: number, b: number) => a + b, 0) / memLatencies.length)
        : 0;

    // Tool metrics
    const toolSucceeded = toolCalls.filter((t: { success: boolean }) => t.success).length;
    const toolFailed = toolCalls.filter((t: { success: boolean }) => !t.success).length;

    // Escalation detection
    const escalated = outcome === "escalated" ||
        thoughts.some((t: { step_name: string }) => t.step_name.includes("escalat"));

    return {
        message_count: messages.length,
        agent_message_count: agentMessages.length,
        customer_message_count: customerMessages.length,
        avg_response_length: avgResponseLength,
        max_response_length: maxResponseLength,
        tool_calls_total: toolCalls.length,
        tool_calls_succeeded: toolSucceeded,
        tool_calls_failed: toolFailed,
        memory_searches: memorySearches,
        memory_hits: memoryHits,
        avg_memory_latency_ms: avgMemoryLatency,
        avg_response_time_ms: avgResponseTime,
        escalated,
        outcome,
        sentiment_score: sentimentScore,
    };
}

// =============================================================================
// Deterministic Score Calculations
// =============================================================================

function scoreEfficiencyDeterministic(signals: DeterministicSignals): number {
    const maxLength = getWhatsAppConfig().maxResponseLength;
    let score = 80; // baseline

    // Penalize excessive back-and-forth (>10 total messages)
    if (signals.message_count > 16) score -= 20;
    else if (signals.message_count > 10) score -= 10;

    // Penalize overly long responses (use configured max_length, not hardcoded)
    if (signals.avg_response_length > maxLength * 1.5) score -= 20;
    else if (signals.avg_response_length > maxLength) score -= 10;

    // Penalize failed tool calls
    if (signals.tool_calls_failed > 2) score -= 15;
    else if (signals.tool_calls_failed > 0) score -= 5;

    // Reward fast response times
    if (signals.avg_response_time_ms > 0 && signals.avg_response_time_ms < 5000) score += 10;
    else if (signals.avg_response_time_ms > 30000) score -= 15;

    return Math.max(0, Math.min(100, score));
}

function scoreContextAwareness(signals: DeterministicSignals): number {
    let score = 30; // baseline without memory usage

    // Reward memory searches
    if (signals.memory_searches > 0) score += 30;

    // Reward memory hits
    if (signals.memory_hits > 0) score += 40;

    // Penalize no memory search at all
    if (signals.memory_searches === 0) score -= 20;

    return Math.max(0, Math.min(100, score));
}

function scoreResolutionQuality(signals: DeterministicSignals): number {
    if (signals.outcome === "resolved") return 100;

    if (signals.escalated) {
        // Appropriate escalation (low sentiment) = good
        if (signals.sentiment_score <= 2) return 80;
        // Premature escalation (high sentiment) = poor
        if (signals.sentiment_score >= 4) return 40;
        return 60;
    }

    if (signals.outcome === "unknown" || signals.outcome === "pending") return 50;
    return 60;
}

function scoreEscalationDeterministic(signals: DeterministicSignals): number | null {
    if (!signals.escalated) return null;

    let score = 60;
    // Low sentiment + escalation = appropriate
    if (signals.sentiment_score <= 2) score += 30;
    // High sentiment + escalation = premature
    if (signals.sentiment_score >= 4) score -= 30;
    // Neutral sentiment
    if (signals.sentiment_score === 3) score += 10;

    return Math.max(0, Math.min(100, score));
}

// =============================================================================
// Step 2: LLM Evaluator
// =============================================================================

async function evaluateWithLLM(
    transcript: string,
    signals: DeterministicSignals,
    thoughtTrail: string,
    context?: { conversationId?: string; phone?: string },
): Promise<QualitativeGrade> {
    const model = await createTrackedLLM({
        provider: "openai",
        model: "gpt-4o-mini",
        callSite: "interaction_grader",
        context,
    });

    // Resolve template placeholders with actual config values
    const config = getWhatsAppConfig();
    const resolvedRules = SUPPORT_SYSTEM_PROMPT
        .replace(/\{business_name\}/g, config.businessName)
        .replace(/\{business_address\}/g, config.businessAddress)
        .replace(/\{business_hours\}/g, config.businessHours)
        .replace(/\{support_phone\}/g, config.supportPhone)
        .replace(/\{store_phone\}/g, process.env.STORE_DIRECT_PHONE ?? config.supportPhone)
        .replace(/\{business_email\}/g, config.businessEmail)
        .replace(/\{max_length\}/g, String(config.maxResponseLength));

    const metricsBlock = `=== INTERACTION METRICS ===
Messages: ${signals.message_count} (customer: ${signals.customer_message_count}, agent: ${signals.agent_message_count})
Avg agent response length: ${signals.avg_response_length} chars (max allowed: ${config.maxResponseLength})
Max agent response length: ${signals.max_response_length} chars
Tool calls: ${signals.tool_calls_total} total, ${signals.tool_calls_succeeded} succeeded, ${signals.tool_calls_failed} failed
Memory searches: ${signals.memory_searches}, hits: ${signals.memory_hits}
Avg response time: ${signals.avg_response_time_ms}ms
Outcome: ${signals.outcome} | Sentiment: ${signals.sentiment_score}/5
Escalated: ${signals.escalated ? "yes" : "no"}`;

    const systemPrompt = `You are an expert QA evaluator for a customer service AI agent at a TechRepair service center.
You will evaluate the agent's performance on a specific conversation.

${metricsBlock}

=== AGENT RULES (the 18 rules the agent must follow) ===
${resolvedRules}

=== THOUGHT TRAIL ===
${thoughtTrail || "(none available)"}

=== INSTRUCTIONS ===
Use the metrics above to inform your evaluation. Flag specific rule violations by number. For over-engineering flags, cite the metric that proves it.
Be concise but thorough. Only flag real issues — don't fabricate problems.`;

    const structuredModel = model.withStructuredOutput(QualitativeGradeSchema);
    return await structuredModel.invoke([
        { role: "system", content: systemPrompt },
        { role: "user", content: `=== CONVERSATION TRANSCRIPT ===\n${transcript}` },
    ]);
}

// =============================================================================
// Step 3: Composite Scoring
// =============================================================================

interface CompositeGrade {
    resolution_quality: number;
    rule_adherence: number;
    efficiency: number;
    context_awareness: number;
    escalation_appropriateness: number | null;
    overall_score: number;
    resolution_explanation: string;
    rule_explanation: string;
    efficiency_explanation: string;
    context_explanation: string;
    escalation_explanation: string | null;
    rule_violations: QualitativeGrade["rule_violations"];
    over_engineering_flags: QualitativeGrade["over_engineering_flags"];
    strengths: string[];
}

function computeComposite(
    signals: DeterministicSignals,
    llm: QualitativeGrade,
): CompositeGrade {
    const resolution = scoreResolutionQuality(signals);
    const ruleAdherence = llm.rule_adherence;

    // Efficiency: 70% deterministic + 30% LLM penalty from over-engineering
    const detEfficiency = scoreEfficiencyDeterministic(signals);
    const oePenalty = Math.min(30, llm.over_engineering_flags.length * 10);
    const efficiency = Math.round(detEfficiency * 0.7 + Math.max(0, 100 - oePenalty) * 0.3);

    const contextAwareness = scoreContextAwareness(signals);

    // Escalation: 60% deterministic + 40% LLM (if applicable)
    const detEscalation = scoreEscalationDeterministic(signals);
    let escalationScore: number | null = null;
    if (detEscalation !== null) {
        const llmEscalation = llm.escalation_assessment ?? detEscalation;
        escalationScore = Math.round(detEscalation * 0.6 + llmEscalation * 0.4);
    }

    // Weighted overall: resolution(25%) + rules(25%) + efficiency(20%) + context(15%) + escalation(15%)
    let overall: number;
    if (escalationScore !== null) {
        overall = Math.round(
            resolution * 0.25 +
            ruleAdherence * 0.25 +
            efficiency * 0.20 +
            contextAwareness * 0.15 +
            escalationScore * 0.15,
        );
    } else {
        // Without escalation, redistribute its 15% weight proportionally
        overall = Math.round(
            resolution * 0.30 +
            ruleAdherence * 0.30 +
            efficiency * 0.22 +
            contextAwareness * 0.18,
        );
    }

    return {
        resolution_quality: resolution,
        rule_adherence: ruleAdherence,
        efficiency,
        context_awareness: contextAwareness,
        escalation_appropriateness: escalationScore,
        overall_score: Math.max(0, Math.min(100, overall)),
        resolution_explanation: `Outcome: ${signals.outcome}, Sentiment: ${signals.sentiment_score}/5`,
        rule_explanation: llm.rule_explanation,
        efficiency_explanation: `${signals.message_count} messages, avg ${signals.avg_response_length} chars/response, ${signals.tool_calls_failed} failed tool calls. ${llm.qualitative_notes}`,
        context_explanation: `Memory searches: ${signals.memory_searches}, hits: ${signals.memory_hits}`,
        escalation_explanation: llm.escalation_explanation ?? null,
        rule_violations: llm.rule_violations,
        over_engineering_flags: llm.over_engineering_flags,
        strengths: llm.strengths,
    };
}

// =============================================================================
// Main Entry Point
// =============================================================================

export async function gradeInteraction(params: GradeInteractionParams): Promise<void> {
    const startMs = Date.now();
    const sb = getSupabaseClient();
    if (!sb) {
        console.warn("[InteractionGrader] No Supabase client — skipping grading");
        return;
    }

    // Step 1: Compute deterministic signals
    const signals = await computeDeterministicSignals(
        params.conversationId,
        params.sentimentScore,
        params.outcome,
    );

    // Fetch thought trail for LLM context
    const { data: thoughts } = await sb
        .from("thought_logs")
        .select("step_name, thought_content, created_at")
        .eq("conversation_id", params.conversationId)
        .order("created_at", { ascending: true });

    const thoughtTrail = (thoughts ?? [])
        .map((t: { step_name: string; thought_content: string; created_at: string }) =>
            `[${t.created_at}] ${t.step_name}: ${t.thought_content}`)
        .join("\n");

    // Step 2: LLM evaluation
    const llmGrade = await evaluateWithLLM(params.transcript, signals, thoughtTrail, {
        conversationId: params.conversationId,
        phone: params.phone,
    });

    // Step 3: Composite
    const grade = computeComposite(signals, llmGrade);

    const latencyMs = Date.now() - startMs;

    // Store in database
    const { error } = await sb.from("interaction_grades").insert({
        interaction_id: params.interactionId,
        conversation_id: params.conversationId,
        phone: params.phone,
        resolution_quality: grade.resolution_quality,
        rule_adherence: grade.rule_adherence,
        efficiency: grade.efficiency,
        context_awareness: grade.context_awareness,
        escalation_appropriateness: grade.escalation_appropriateness,
        overall_score: grade.overall_score,
        resolution_explanation: grade.resolution_explanation,
        rule_explanation: grade.rule_explanation,
        efficiency_explanation: grade.efficiency_explanation,
        context_explanation: grade.context_explanation,
        escalation_explanation: grade.escalation_explanation,
        rule_violations: grade.rule_violations,
        over_engineering_flags: grade.over_engineering_flags,
        strengths: grade.strengths,
        deterministic_signals: signals,
        model_used: "gpt-4o-mini",
        grading_latency_ms: latencyMs,
    });

    if (error) {
        console.error("[InteractionGrader] Failed to store grade:", error);
        return;
    }

    console.info(
        `[InteractionGrader] Graded ${params.conversationId}: overall=${grade.overall_score}, ` +
        `rules=${grade.rule_adherence}, efficiency=${grade.efficiency}, ` +
        `violations=${grade.rule_violations.length}, oe_flags=${grade.over_engineering_flags.length} ` +
        `(${latencyMs}ms)`,
    );
}
