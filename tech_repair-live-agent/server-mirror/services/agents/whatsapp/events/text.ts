/**
 * Shared text helpers for event detectors.
 * Accents break `\b` word boundaries in JS regex (ó/í are non-word chars), so
 * detectors normalize first and match accent-free patterns.
 */

/** Lowercase + strip diacritics: "ya me llegó" → "ya me llego". */
export function normalize(text: string): string {
    return text
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .toLowerCase()
        .trim();
}
