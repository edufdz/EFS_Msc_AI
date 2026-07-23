/**
 * Supabase Call Center Logger
 * ===========================
 * Comprehensive logging interface to Supabase for call center analytics:
 * - Call sessions and metadata
 * - Participants and metrics
 * - Transcripts and segments
 * - Performance metrics
 * - Sentiment analysis
 * - Tool invocations
 * - Tags and notes
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { getSupabaseClient } from "./supabase";

// =============================================================================
// Helper
// =============================================================================

function utcNow(): string {
    return new Date().toISOString();
}

/** Remove keys whose values are null or undefined. */
function stripNulls(obj: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(
        Object.entries(obj).filter(([, v]) => v != null),
    );
}

// =============================================================================
// CallCenterLogger
// =============================================================================

export class CallCenterLogger {
    private client: SupabaseClient | null;

    constructor(client?: SupabaseClient | null) {
        this.client = client ?? null;
    }

    private ensureClient(): SupabaseClient {
        if (!this.client) {
            this.client = getSupabaseClient();
        }
        if (!this.client) {
            throw new Error("Supabase not configured for CallCenterLogger");
        }
        return this.client;
    }

    // ==========================================================================
    // CALL MANAGEMENT
    // ==========================================================================

    async startCall(params: {
        roomSid: string;
        roomName: string;
        callDirection: "inbound" | "outbound";
        callChannel?: "phone" | "direct" | "web" | "test";
        customerPhone?: string;
        customerEmail?: string;
        customerName?: string;
        customerId?: string;
        queueName?: string;
        campaignName?: string;
        svcOrderNo?: string;
        metadata?: Record<string, unknown>;
    }): Promise<string> {
        const client = this.ensureClient();
        const data = stripNulls({
            room_sid: params.roomSid,
            room_name: params.roomName,
            call_direction: params.callDirection,
            // call_channel: medium axis. Defaults to 'phone' (column default in DB)
            // when omitted, which is the right answer for SIP-routed calls. Direct
            // and test paths must pass it explicitly.
            call_channel: params.callChannel,
            call_status: "in_progress",
            started_at: utcNow(),
            customer_phone: params.customerPhone,
            customer_email: params.customerEmail,
            customer_name: params.customerName,
            customer_id: params.customerId,
            queue_name: params.queueName,
            campaign_name: params.campaignName,
            svc_order_no: params.svcOrderNo,
            metadata: params.metadata ?? {},
        });
        const result = await client.from("calls").insert(data).select("id").single();
        if (result.error || !result.data) {
            throw new Error(`Failed to insert call: ${result.error?.message ?? "no data returned"}`);
        }
        return result.data.id as string;
    }

    /**
     * Find an existing call row (created by webhook) or create a new one.
     * Eliminates the duplicate-row race condition between webhook and agent.
     */
    async findOrCreateCall(params: {
        roomSid: string;
        roomName: string;
        callDirection: "inbound" | "outbound";
        callChannel?: "phone" | "direct" | "web" | "test";
        customerPhone?: string;
        customerEmail?: string;
        customerName?: string;
        customerId?: string;
        queueName?: string;
        campaignName?: string;
        svcOrderNo?: string;
        metadata?: Record<string, unknown>;
    }): Promise<string> {
        const client = this.ensureClient();

        // 1. Try to find an existing row created by the webhook (matched by room_name)
        const existing = await client
            .from("calls")
            .select("id")
            .eq("room_name", params.roomName)
            .order("created_at", { ascending: false })
            .limit(1)
            .maybeSingle();

        if (existing.data?.id) {
            // Update the existing row with agent metadata
            const updateData = stripNulls({
                room_sid: params.roomSid,
                customer_phone: params.customerPhone,
                customer_email: params.customerEmail,
                customer_name: params.customerName,
                customer_id: params.customerId,
                queue_name: params.queueName,
                campaign_name: params.campaignName,
                svc_order_no: params.svcOrderNo,
                metadata: params.metadata ?? {},
            });
            await client.from("calls").update(updateData).eq("id", existing.data.id);
            console.log(`[CallCenterLogger] Found existing call by room_name: ${existing.data.id}`);
            return existing.data.id as string;
        }

        // 2. Fallback: try by room_sid (webhook stores this on room_started)
        if (params.roomSid && params.roomSid !== params.roomName) {
            const bySid = await client
                .from("calls")
                .select("id")
                .eq("room_sid", params.roomSid)
                .order("created_at", { ascending: false })
                .limit(1)
                .maybeSingle();

            if (bySid.data?.id) {
                const updateData = stripNulls({
                    room_name: params.roomName,
                    customer_phone: params.customerPhone,
                    customer_email: params.customerEmail,
                    customer_name: params.customerName,
                    customer_id: params.customerId,
                    queue_name: params.queueName,
                    campaign_name: params.campaignName,
                    svc_order_no: params.svcOrderNo,
                    metadata: params.metadata ?? {},
                });
                await client.from("calls").update(updateData).eq("id", bySid.data.id);
                console.log(`[CallCenterLogger] Found existing call by room_sid: ${bySid.data.id}`);
                return bySid.data.id as string;
            }
        }

        // 3. No existing row (console mode or webhook hasn't fired) — insert new
        console.log("[CallCenterLogger] No existing call row found, creating new one");
        return this.startCall(params);
    }

    async endCall(params: {
        callId: string;
        callOutcome?: string;
        dispositionCode?: string;
        dispositionNotes?: string;
        audioQualityScore?: number;
        recordingUrl?: string;
    }): Promise<void> {
        const client = this.ensureClient();
        const data = stripNulls({
            call_status: "completed",
            ended_at: utcNow(),
            call_outcome: params.callOutcome,
            disposition_code: params.dispositionCode,
            disposition_notes: params.dispositionNotes,
            audio_quality_score: params.audioQualityScore,
            recording_url: params.recordingUrl,
        });
        await client.from("calls").update(data).eq("id", params.callId);
    }

    // ==========================================================================
    // PARTICIPANT MANAGEMENT
    // ==========================================================================

    async addParticipant(params: {
        callId: string;
        participantSid: string;
        participantIdentity: string;
        participantType: "agent" | "customer" | "supervisor" | "system";
        participantName?: string;
        agentId?: string;
        agentEmail?: string;
        agentTeam?: string;
        metadata?: Record<string, unknown>;
    }): Promise<string> {
        const client = this.ensureClient();
        const data = {
            call_id: params.callId,
            participant_sid: params.participantSid,
            participant_identity: params.participantIdentity,
            participant_type: params.participantType,
            participant_name: params.participantName,
            agent_id: params.agentId,
            agent_email: params.agentEmail,
            agent_team: params.agentTeam,
            joined_at: utcNow(),
            metadata: params.metadata ?? {},
        };
        const result = await client.from("participants").insert(data).select("id").single();
        if (result.error || !result.data) {
            throw new Error(`Failed to insert participant: ${result.error?.message ?? "no data returned"}`);
        }
        return result.data.id as string;
    }

    async updateParticipantMetrics(params: {
        participantId: string;
        speakingTimeSeconds?: number;
        listeningTimeSeconds?: number;
        mutedTimeSeconds?: number;
        avgLatencyMs?: number;
        packetLossPercentage?: number;
    }): Promise<void> {
        const client = this.ensureClient();
        const data = stripNulls({
            speaking_time_seconds: params.speakingTimeSeconds,
            listening_time_seconds: params.listeningTimeSeconds,
            muted_time_seconds: params.mutedTimeSeconds,
            avg_latency_ms: params.avgLatencyMs,
            packet_loss_percentage: params.packetLossPercentage,
        });
        if (Object.keys(data).length > 0) {
            await client.from("participants").update(data).eq("id", params.participantId);
        }
    }

    async participantLeft(participantId: string): Promise<void> {
        const client = this.ensureClient();
        await client.from("participants").update({ left_at: utcNow() }).eq("id", participantId);
    }

    // ==========================================================================
    // TRANSCRIPT MANAGEMENT
    // ==========================================================================

    async createTranscript(params: {
        callId: string;
        transcriptionEngine?: string;
        language?: string;
    }): Promise<string> {
        const client = this.ensureClient();
        const data = {
            call_id: params.callId,
            transcription_engine: params.transcriptionEngine ?? "deepgram",
            language: params.language ?? "en",
            transcription_started_at: utcNow(),
        };
        const result = await client.from("transcripts").insert(data).select("id").single();
        if (result.error || !result.data) {
            throw new Error(`Failed to insert transcript: ${result.error?.message ?? "no data returned"}`);
        }
        return result.data.id as string;
    }

    async addTranscriptSegment(params: {
        callId: string;
        transcriptId: string;
        text: string;
        speakerLabel: string;
        sequenceNumber: number;
        startTimeSeconds: number;
        endTimeSeconds: number;
        participantId?: string;
        confidenceScore?: number;
        words?: Array<Record<string, unknown>>;
    }): Promise<string> {
        const client = this.ensureClient();
        const duration = params.endTimeSeconds - params.startTimeSeconds;
        const data = {
            transcript_id: params.transcriptId,
            call_id: params.callId,
            participant_id: params.participantId ?? null,
            text: params.text,
            speaker_label: params.speakerLabel,
            sequence_number: params.sequenceNumber,
            start_time_seconds: params.startTimeSeconds,
            end_time_seconds: params.endTimeSeconds,
            duration_seconds: duration,
            confidence_score: params.confidenceScore,
            words: params.words,
        };
        const result = await client.from("transcript_segments").insert(data).select("id").single();
        if (result.error || !result.data) {
            throw new Error(`Failed to insert transcript segment: ${result.error?.message ?? "no data returned"}`);
        }
        return result.data.id as string;
    }

    async finalizeTranscript(params: {
        transcriptId: string;
        fullTranscript: string;
        summary?: string;
        wordCount?: number;
        confidenceScore?: number;
    }): Promise<void> {
        const client = this.ensureClient();
        const data = {
            full_transcript: params.fullTranscript,
            summary: params.summary,
            word_count: params.wordCount ?? params.fullTranscript.split(/\s+/).length,
            character_count: params.fullTranscript.length,
            confidence_score: params.confidenceScore,
            transcription_completed_at: utcNow(),
        };
        await client.from("transcripts").update(data).eq("id", params.transcriptId);
    }

    // ==========================================================================
    // METRICS AND ANALYTICS
    // ==========================================================================

    async addCallMetrics(params: {
        callId: string;
        avgAudioQuality?: number;
        totalInterruptions?: number;
        agentTalkTimeSeconds?: number;
        customerTalkTimeSeconds?: number;
        totalSilenceDurationSeconds?: number;
        totalHoldDurationSeconds?: number;
        avgLatencyMs?: number;
        [key: string]: unknown;
    }): Promise<void> {
        const client = this.ensureClient();
        const { callId, ...rest } = params;
        const data = stripNulls({
            call_id: callId,
            avg_audio_quality: rest.avgAudioQuality,
            total_interruptions: rest.totalInterruptions ?? 0,
            agent_talk_time_seconds: rest.agentTalkTimeSeconds ?? 0,
            customer_talk_time_seconds: rest.customerTalkTimeSeconds ?? 0,
            total_silence_duration_seconds: rest.totalSilenceDurationSeconds ?? 0,
            total_hold_duration_seconds: rest.totalHoldDurationSeconds ?? 0,
            avg_latency_ms: rest.avgLatencyMs,
        });
        await client.from("call_metrics").insert(data);
    }

    async addAgentPerformance(params: {
        callId: string;
        participantId: string;
        agentId: string;
        agentName?: string;
        overallPerformanceScore?: number;
        customerSatisfactionScore?: number;
        firstCallResolution?: boolean;
        empathyScore?: number;
        professionalismScore?: number;
    }): Promise<void> {
        const client = this.ensureClient();
        const data = stripNulls({
            call_id: params.callId,
            participant_id: params.participantId,
            agent_id: params.agentId,
            agent_name: params.agentName,
            overall_performance_score: params.overallPerformanceScore,
            customer_satisfaction_score: params.customerSatisfactionScore,
            first_call_resolution: params.firstCallResolution,
            empathy_score: params.empathyScore,
            professionalism_score: params.professionalismScore,
        });
        await client.from("agent_performance").insert(data);
    }

    // ==========================================================================
    // SENTIMENT ANALYSIS
    // ==========================================================================

    async addSentiment(params: {
        callId: string;
        sentiment: string;
        sentimentScore: number;
        transcriptSegmentId?: string;
        speakerType?: string;
        speakerIdentity?: string;
        primaryEmotion?: string;
        confidence?: number;
        analysisEngine?: string;
    }): Promise<void> {
        const client = this.ensureClient();
        const data = {
            call_id: params.callId,
            transcript_segment_id: params.transcriptSegmentId ?? null,
            sentiment: params.sentiment,
            sentiment_score: params.sentimentScore,
            speaker_type: params.speakerType,
            speaker_identity: params.speakerIdentity,
            primary_emotion: params.primaryEmotion,
            confidence: params.confidence,
            analysis_engine: params.analysisEngine ?? "openai",
        };
        await client.from("sentiment_analysis").insert(data);
    }

    // ==========================================================================
    // TOOL INVOCATIONS
    // ==========================================================================

    async logToolInvocation(params: {
        callId: string;
        toolName: string;
        success: boolean;
        inputParameters?: Record<string, unknown>;
        outputResult?: Record<string, unknown>;
        executionTimeMs?: number;
        errorMessage?: string;
        transcriptSegmentId?: string;
        toolDescription?: string;
        toolCategory?: string;
    }): Promise<void> {
        const client = this.ensureClient();
        const data = {
            call_id: params.callId,
            transcript_segment_id: params.transcriptSegmentId ?? null,
            tool_name: params.toolName,
            tool_description: params.toolDescription,
            tool_category: params.toolCategory,
            input_parameters: params.inputParameters,
            output_result: params.outputResult,
            execution_time_ms: params.executionTimeMs,
            success: params.success,
            error_message: params.errorMessage,
            invocation_timestamp: utcNow(),
        };
        await client.from("tool_invocations").insert(data);
    }

    // ==========================================================================
    // TAGGING AND NOTES
    // ==========================================================================

    async addTag(params: {
        callId: string;
        tagKey: string;
        tagValue: string;
        tagCategory?: string;
        taggedBy?: string;
        confidence?: number;
    }): Promise<void> {
        const client = this.ensureClient();
        const data = {
            call_id: params.callId,
            tag_key: params.tagKey,
            tag_value: params.tagValue,
            tag_category: params.tagCategory,
            tagged_by: params.taggedBy ?? "system",
            confidence: params.confidence,
            tagged_at: utcNow(),
        };
        await client.from("call_tags").insert(data);
    }

    async addNote(params: {
        callId: string;
        noteText: string;
        authorId: string;
        noteType?: string;
        noteTitle?: string;
        authorName?: string;
        authorRole?: string;
        isPrivate?: boolean;
    }): Promise<void> {
        const client = this.ensureClient();
        const data = {
            call_id: params.callId,
            note_text: params.noteText,
            note_type: params.noteType,
            note_title: params.noteTitle,
            author_id: params.authorId,
            author_name: params.authorName,
            author_role: params.authorRole,
            is_private: params.isPrivate ?? false,
        };
        await client.from("call_notes").insert(data);
    }

    // ==========================================================================
    // OBSERVABILITY (memory + thought logging)
    // ==========================================================================

    async logMemoryRetrieval(params: {
        callId?: string;
        conversationId?: string;
        phone?: string;
        query: string;
        foundMemories: string[];
        latencyMs?: number;
    }): Promise<void> {
        return logMemoryRetrieval(this.ensureClient(), params);
    }

    async logAgentThought(params: {
        callId?: string;
        conversationId?: string;
        phone?: string;
        stepName: string;
        thoughtContent: string;
    }): Promise<void> {
        return logAgentThought(this.ensureClient(), params);
    }
}

// =============================================================================
// Standalone Observability Functions
// =============================================================================
// These are exported as standalone functions so WhatsApp nodes (which have no
// CallCenterLogger instance) can call them directly with any SupabaseClient.

/**
 * Log a semantic memory retrieval to `memory_logs`.
 * Fire-and-forget safe — errors are swallowed (non-throwing).
 */
export async function logMemoryRetrieval(
    client: SupabaseClient,
    params: {
        callId?: string;
        conversationId?: string;
        phone?: string;
        query: string;
        foundMemories: string[];
        latencyMs?: number;
        /** Retrieval outcome: hit (facts found), empty (no facts), timeout, error */
        status?: "hit" | "empty" | "timeout" | "error";
    },
): Promise<void> {
    try {
        await client.from("memory_logs").insert({
            call_id: params.callId ?? null,
            conversation_id: params.conversationId ?? null,
            phone: params.phone ?? null,
            query: params.query,
            found_memories: params.foundMemories,
            memory_count: params.foundMemories.length,
            latency_ms: params.latencyMs ?? null,
            status: params.status ?? "hit",
        });
    } catch (err) {
        console.warn("[supabase-logger] logMemoryRetrieval failed (non-fatal):", err);
    }
}

/**
 * Log an agent decision step to `thought_logs`.
 * Fire-and-forget safe — errors are swallowed (non-throwing).
 */
export async function logAgentThought(
    client: SupabaseClient,
    params: {
        callId?: string;
        conversationId?: string;
        phone?: string;
        stepName: string;
        thoughtContent: string;
    },
): Promise<void> {
    try {
        await client.from("thought_logs").insert({
            call_id: params.callId ?? null,
            conversation_id: params.conversationId ?? null,
            phone: params.phone ?? null,
            step_name: params.stepName,
            thought_content: params.thoughtContent,
        });
    } catch (err) {
        console.warn("[supabase-logger] logAgentThought failed (non-fatal):", err);
    }
}

/**
 * Log a tool invocation to `tool_invocations`.
 * Standalone version for WhatsApp nodes that have no CallCenterLogger.
 * Fire-and-forget safe — errors are swallowed (non-throwing).
 */
export async function logToolInvocation(
    client: SupabaseClient,
    params: {
        callId?: string;
        conversationId?: string;
        toolName: string;
        success: boolean;
        inputParameters?: Record<string, unknown>;
        outputResult?: Record<string, unknown>;
        executionTimeMs?: number;
        errorMessage?: string;
        toolCategory?: string;
    },
): Promise<void> {
    try {
        await client.from("tool_invocations").insert({
            call_id: params.callId ?? null,
            tool_name: params.toolName,
            tool_category: params.toolCategory ?? "whatsapp",
            input_parameters: params.inputParameters ?? {},
            output_result: params.outputResult ?? {},
            execution_time_ms: params.executionTimeMs ?? null,
            success: params.success,
            error_message: params.errorMessage ?? null,
            invocation_timestamp: utcNow(),
        });
    } catch (err) {
        console.warn("[supabase-logger] logToolInvocation failed (non-fatal):", err);
    }
}

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Normalize a 5-level sentiment enum to a 3-bucket summary (positive/neutral/negative).
 * Maps very_positive → positive, very_negative → negative.
 */
export function normalizeSentimentBucket(
    raw: string | null | undefined,
): "positive" | "neutral" | "negative" {
    const label = (raw || "neutral").toLowerCase();
    if (label === "very_positive" || label === "positive") return "positive";
    if (label === "very_negative" || label === "negative") return "negative";
    return "neutral";
}

/**
 * Map a sentiment score (-1.0 to 1.0) to a sentiment type.
 */
export function mapSentimentScoreToType(
    score: number,
): "very_negative" | "negative" | "neutral" | "positive" | "very_positive" {
    if (score <= -0.6) return "very_negative";
    if (score <= -0.2) return "negative";
    if (score <= 0.2) return "neutral";
    if (score <= 0.6) return "positive";
    return "very_positive";
}

/**
 * Map the extraction's 1-5 sentiment scale to the DB sentiment_type enum + normalized score.
 * 1=very negative → -1.0, 3=neutral → 0.0, 5=very positive → 1.0
 */
export function mapExtractedSentiment(extractionScore: number): {
    sentiment: "very_negative" | "negative" | "neutral" | "positive" | "very_positive";
    sentimentScore: number;
} {
    // Convert 1-5 scale to -1.0 .. 1.0
    const normalized = (extractionScore - 3) / 2;
    const clamped = Math.max(-1, Math.min(1, normalized));
    return {
        sentiment: mapSentimentScoreToType(clamped),
        sentimentScore: clamped,
    };
}
