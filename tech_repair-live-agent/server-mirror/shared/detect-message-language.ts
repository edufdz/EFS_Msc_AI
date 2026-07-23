/**
 * Detect Message Language
 * =======================
 * Cheap keyword-based ES/EN classifier used by the memory resolver's
 * `aggregatePreferredLanguage` helper. Returns a definite 'es' or 'en' —
 * defaults to 'es' on ambiguous input (matches the convention used by the
 * WhatsApp orchestrator's private `detectMessageLanguage` method in
 * `services/orchestrator/whatsapp.ts:731`, which this mirrors).
 *
 * Known bias: short / ambiguous messages lean 'es'. The aggregator filters
 * ≤3-word messages before calling this, which is where the bias lands
 * softest.
 *
 * TODO: dedupe with the orchestrator's copy when that file is next touched.
 */

const ENGLISH_MARKERS =
    /\b(thank|thanks|hello|please|help|need|want|will|wait|waiting|appreciate|sorry|okay|yes|and|the|you|your|have|got|can|could|would)\b/i;
const SPANISH_MARKERS =
    /\b(gracias|hola|por\s+favor|ayuda|necesito|quiero|esper|quedo|pendiente|amable|muchas|claro|perfecto|bueno|estoy|est[aá])\b|[ñáéíóú¡¿]/i;

export function detectMessageLanguage(text: string): "es" | "en" {
    const lower = text.toLowerCase();
    const hasEnglish = ENGLISH_MARKERS.test(lower);
    const hasSpanish = SPANISH_MARKERS.test(lower);
    if (hasEnglish && !hasSpanish) return "en";
    return "es";
}
