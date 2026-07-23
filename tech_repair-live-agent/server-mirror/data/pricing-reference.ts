/**
 * AI Provider Pricing Reference
 * ===============================
 * Raw pricing from provider websites, used to calculate per-minute estimates.
 * Pricing is NOT available via API — must be manually verified from provider pricing pages.
 *
 * LAST VERIFIED: 2026-02-14
 *
 * Sources:
 * - OpenAI: https://developers.openai.com/api/docs/pricing/
 * - Deepgram: https://deepgram.com/pricing (Pay-As-You-Go tier)
 * - Cartesia: https://cartesia.ai/pricing (credit-based, Scale plan ~$299/8M credits)
 * - ElevenLabs: https://elevenlabs.io/pricing/api (~$0.20/1K chars on Scale plan)
 *
 * HOW TO UPDATE:
 * 1. Visit each provider's pricing page
 * 2. Update the raw pricing below
 * 3. Update LAST_VERIFIED date
 * 4. Run the conversion helpers to recalculate per-minute estimates
 */

export const PRICING_LAST_VERIFIED = '2026-02-14'

// =============================================================================
// CONVERSION ASSUMPTIONS (for per-minute voice conversation estimates)
// =============================================================================

/**
 * Average characters of speech synthesized per minute (~150 words * 4 chars/word)
 * This is the TTS output — how much text the agent speaks per minute.
 */
export const AVG_TTS_CHARS_PER_MINUTE = 600

/**
 * Approximate LLM token usage per minute of voice conversation.
 * Accounts for: system prompt amortized, conversation history, agent responses.
 * ~2 turns/min, ~1000 input tokens + 200 output tokens per turn.
 */
export const AVG_LLM_INPUT_TOKENS_PER_MINUTE = 2000
export const AVG_LLM_OUTPUT_TOKENS_PER_MINUTE = 400

// =============================================================================
// RAW PROVIDER PRICING
// =============================================================================

/** Anthropic LLM pricing per 1M tokens */
export const ANTHROPIC_LLM_PRICING: Record<string, {
  input: number; output: number; cacheRead?: number; cacheWrite?: number
}> = {
  'claude-sonnet-4-20250514':  { input: 3.00,  output: 15.00, cacheRead: 0.30,  cacheWrite: 3.75 },
  'claude-haiku-4-5-20251001': { input: 0.80,  output: 4.00,  cacheRead: 0.08,  cacheWrite: 1.00 },
  'claude-haiku-3-5-20241022': { input: 0.80,  output: 4.00,  cacheRead: 0.08,  cacheWrite: 1.00 },
  'claude-opus-4-20250514':    { input: 15.00, output: 75.00, cacheRead: 1.50,  cacheWrite: 18.75 },
}

/** Google Gemini LLM pricing per 1M tokens (text + image + audio + video tokens billed at same rate for Flash tier) */
export const GOOGLE_LLM_PRICING: Record<string, {
  input: number; output: number
}> = {
  'gemini-2.0-flash':      { input: 0.10, output: 0.40 },
  'gemini-2.0-flash-lite': { input: 0.075, output: 0.30 },
  'gemini-2.5-flash':      { input: 0.30, output: 2.50 },
  'gemini-2.5-pro':        { input: 1.25, output: 10.00 },
}

/** OpenAI LLM pricing per 1M tokens */
export const OPENAI_LLM_PRICING: Record<string, { input: number; output: number }> = {
  'gpt-5-nano':     { input: 0.05,  output: 0.40 },
  'gpt-5-mini':     { input: 0.25,  output: 2.00 },
  'gpt-5':          { input: 1.25,  output: 10.00 },
  'gpt-5.1':        { input: 1.25,  output: 10.00 },
  'gpt-5.2':        { input: 1.75,  output: 14.00 },
  'gpt-4.1-nano':   { input: 0.10,  output: 0.40 },
  'gpt-4.1-mini':   { input: 0.40,  output: 1.60 },
  'gpt-4.1':        { input: 2.00,  output: 8.00 },
  'gpt-4o-mini':    { input: 0.15,  output: 0.60 },
  'gpt-4o':         { input: 2.50,  output: 10.00 },
  'o3-mini':        { input: 1.10,  output: 4.40 },
  'o3':             { input: 2.00,  output: 8.00 },
  'gpt-4-turbo':    { input: 10.00, output: 30.00 },
  'gpt-3.5-turbo':  { input: 0.50,  output: 1.50 },
}

/** OpenAI TTS pricing per 1M characters */
export const OPENAI_TTS_PRICING: Record<string, number> = {
  'tts-1':           15.00,
  'tts-1-hd':        30.00,
  'gpt-4o-mini-tts': 12.00, // ~$0.60/1M input tokens + audio output
}

/** OpenAI STT pricing per minute */
export const OPENAI_STT_PRICING: Record<string, number> = {
  'whisper-1':               0.006,
  'gpt-4o-transcribe':       0.006,
  'gpt-4o-mini-transcribe':  0.003,
}

/** Deepgram STT pricing per minute (Pay-As-You-Go) */
export const DEEPGRAM_STT_PRICING: Record<string, number> = {
  'nova-3':            0.0077,
  'nova-3-multi':      0.0092,
  'nova-2':            0.0058,
  'nova-2-medical':    0.0058,
  'nova-2-phonecall':  0.0058,
  'flux':              0.0077,
}

/** Deepgram TTS pricing per 1K characters */
export const DEEPGRAM_TTS_PRICING: Record<string, number> = {
  'aura-2':  0.030,
  'aura':    0.015,
}

/**
 * Cartesia pricing (credit-based).
 * TTS: 1 credit/char, STT: 1 credit/sec
 * Scale plan: $299/8M credits → $0.0000374/credit
 * We use Scale plan pricing as reference.
 */
export const CARTESIA_CREDIT_COST = 299 / 8_000_000 // ~$0.0000374/credit

/** Cartesia TTS: 1 credit per character → cost/char = CARTESIA_CREDIT_COST */
export const CARTESIA_TTS_COST_PER_CHAR = CARTESIA_CREDIT_COST

/** Cartesia STT: 1 credit per second → cost/min = 60 * CARTESIA_CREDIT_COST */
export const CARTESIA_STT_COST_PER_MINUTE = 60 * CARTESIA_CREDIT_COST // ~$0.0022/min

// =============================================================================
// VOICE INFRASTRUCTURE PRICING (LiveKit + Twilio)
// =============================================================================
// Used by the voice-usage cost tracking pipeline (migration 20260512000000).
// All rates are USD per the listed unit. Update here when the contract changes;
// historical voice_usage rows store the rate that was applied at write time,
// so retuning these constants doesn't retroactively rewrite history.

/**
 * LiveKit Cloud — Ship plan overage rates. Verify against next invoice.
 * Cost model: $/participant-minute (audio) + $/track-minute for egress.
 */
export const LIVEKIT_PARTICIPANT_PER_MIN  = 0.0030
export const LIVEKIT_TRACK_EGRESS_PER_MIN = 0.01

/**
 * Twilio — Mexico DID, blended outbound rate.
 * Mexico has had number portability since 2015 — the +521 prefix can't
 * classify mobile vs landline. Use one blended outbound rate (worst case:
 * mobile) until per-call `Call.price` ingestion lands in a follow-up PR.
 * See tech_repair_mexico_phone_portability memory.
 */
export const TWILIO_MX_INBOUND_PER_MIN  = 0.0070
export const TWILIO_MX_OUTBOUND_PER_MIN = 0.1290

/**
 * ElevenLabs pricing (credit-based).
 * Standard models: 1 credit/char, Flash/Turbo: 0.5 credits/char
 * Scale plan: $330/2M chars = $0.000165/char for standard
 * Approximate: ~$0.20/1K chars for standard, ~$0.10/1K for Flash
 */
export const ELEVENLABS_TTS_PER_1K_CHARS: Record<string, number> = {
  'eleven_v3':               0.20,
  'eleven_multilingual_v2':  0.20,
  'eleven_flash_v2_5':       0.10,
  'eleven_flash_v2':         0.10,
  'eleven_turbo_v2_5':       0.10,
  'eleven_turbo_v2':         0.10,
}

// =============================================================================
// OPENAI REALTIME API PRICING (per 1M tokens)
// =============================================================================

/**
 * OpenAI Realtime API pricing.
 * audioInput/audioOutput = per 1M audio tokens
 * textInput = per 1M text tokens (system prompt, tool calls)
 *
 * Assumptions for per-minute estimate:
 * ~1500 audio tokens in (30s user speech) + 1500 audio tokens out (30s agent speech)
 * + ~500 text tokens (system prompt amortized + tool definitions)
 */
export const OPENAI_REALTIME_PRICING: Record<string, { audioInput: number; audioOutput: number; textInput: number }> = {
  'gpt-realtime':                  { audioInput: 32,  audioOutput: 64,  textInput: 4 },
  'gpt-realtime-mini':             { audioInput: 10,  audioOutput: 20,  textInput: 0.60 },
  'gpt-4o-realtime-preview':       { audioInput: 40,  audioOutput: 80,  textInput: 5 },
  'gpt-4o-mini-realtime-preview':  { audioInput: 10,  audioOutput: 20,  textInput: 0.60 },
}

export const AVG_REALTIME_AUDIO_TOKENS_IN_PER_MINUTE = 1500
export const AVG_REALTIME_AUDIO_TOKENS_OUT_PER_MINUTE = 1500
export const AVG_REALTIME_TEXT_TOKENS_PER_MINUTE = 500

// =============================================================================
// PER-MINUTE ESTIMATORS
// =============================================================================

/** Estimate LLM cost per minute of voice conversation */
export function estimateLlmPerMinute(modelId: string): number | undefined {
  const pricing = OPENAI_LLM_PRICING[modelId]
  if (!pricing) return undefined
  const inputCost = (AVG_LLM_INPUT_TOKENS_PER_MINUTE * pricing.input) / 1_000_000
  const outputCost = (AVG_LLM_OUTPUT_TOKENS_PER_MINUTE * pricing.output) / 1_000_000
  return inputCost + outputCost
}

/** Estimate TTS cost per minute based on ~600 chars/min of synthesized speech */
export function estimateTtsPerMinute(providerId: string, modelId: string): number | undefined {
  if (providerId === 'openai') {
    const per1M = OPENAI_TTS_PRICING[modelId]
    if (per1M == null) return undefined
    return (AVG_TTS_CHARS_PER_MINUTE * per1M) / 1_000_000
  }
  if (providerId === 'deepgram') {
    const per1K = DEEPGRAM_TTS_PRICING[modelId]
    if (per1K == null) return undefined
    return (AVG_TTS_CHARS_PER_MINUTE / 1000) * per1K
  }
  if (providerId === 'cartesia') {
    return AVG_TTS_CHARS_PER_MINUTE * CARTESIA_TTS_COST_PER_CHAR
  }
  if (providerId === 'elevenlabs') {
    const per1K = ELEVENLABS_TTS_PER_1K_CHARS[modelId]
    if (per1K == null) return undefined
    return (AVG_TTS_CHARS_PER_MINUTE / 1000) * per1K
  }
  return undefined
}

/** Get STT cost per minute (already priced per minute for most providers) */
export function estimateSttPerMinute(providerId: string, modelId: string): number | undefined {
  if (providerId === 'deepgram') return DEEPGRAM_STT_PRICING[modelId]
  if (providerId === 'openai') return OPENAI_STT_PRICING[modelId]
  if (providerId === 'cartesia') return CARTESIA_STT_COST_PER_MINUTE
  return undefined
}

/** Estimate OpenAI Realtime API cost per minute of conversation */
export function estimateRealtimePerMinute(modelId: string): number | undefined {
  const pricing = OPENAI_REALTIME_PRICING[modelId]
  if (!pricing) return undefined
  const audioInCost = (AVG_REALTIME_AUDIO_TOKENS_IN_PER_MINUTE * pricing.audioInput) / 1_000_000
  const audioOutCost = (AVG_REALTIME_AUDIO_TOKENS_OUT_PER_MINUTE * pricing.audioOutput) / 1_000_000
  const textCost = (AVG_REALTIME_TEXT_TOKENS_PER_MINUTE * pricing.textInput) / 1_000_000
  return audioInCost + audioOutCost + textCost
}
