/**
 * Aggregate Preferred Language
 * ============================
 * Given a list of recent inbound messages, determine the customer's
 * preferred language for the memory prompt block. Filters out short /
 * ambiguous messages (≤3 words) to reduce detector noise from single-word
 * replies like "ok", "gracias", "thanks", then applies an 80/20 vote over
 * the substantive remainder.
 *
 * Returns null when we don't have enough signal — callers should then omit
 * the language block entirely rather than guess.
 */

import { detectMessageLanguage } from "./detect-message-language";

/** Words-per-message threshold below which a message is considered
 * non-substantive and excluded from the vote. Tunable via this constant. */
export const MIN_WORDS_PER_MESSAGE = 4;

export type PreferredLanguage = "es" | "en" | "mixed" | null;

export function aggregatePreferredLanguage(
    messages: Array<{ text_body: string | null; created_at: string }>,
): PreferredLanguage {
    if (messages.length < 3) return null;

    const substantive = messages.filter((m) => {
        const body = (m.text_body ?? "").trim();
        if (!body) return false;
        return body.split(/\s+/).length >= MIN_WORDS_PER_MESSAGE;
    });
    if (substantive.length < 3) return null;

    const langs = substantive.map((m) =>
        detectMessageLanguage(m.text_body ?? ""),
    );

    const esCount = langs.filter((l) => l === "es").length;
    const esRatio = esCount / langs.length;

    if (esRatio > 0.8) return "es";
    if (esRatio < 0.2) return "en";
    return "mixed";
}
