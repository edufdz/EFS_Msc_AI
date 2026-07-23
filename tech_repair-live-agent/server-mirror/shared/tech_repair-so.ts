/**
 * TechRepair Service Order Number Helpers
 * ====================================
 * TechRepair GSPN service-order numbers observed in the tech_repair-next codebase
 * are plain 10-digit numeric strings starting with `4`. Verified examples
 * from the repo: 4123456789, 4498001234, 4412345678, 4498765432. The tour
 * dummy data sometimes prefixes with "SVC" (e.g. "SVC4412345678") but the
 * raw `service_orders.svc_order_no` is always the bare 10-digit form.
 *
 * PRE-MERGE CHECK: spot-check `SELECT svc_order_no FROM service_orders LIMIT 20;`
 * in production to confirm the `^4\d{9}$` assumption holds. If a non-4
 * leading digit appears, loosen the regex accordingly (e.g. `^[4-5]\d{9}$`).
 */

/**
 * Matches TechRepair SO numbers embedded in free text (word-boundary anchored).
 * Global flag so `.match()` returns every occurrence in a message.
 */
export const TECH_REPAIR_SO_REGEX = /\b4\d{9}\b/g;

/**
 * Decide whether a customer message should invalidate the cached
 * `ResolvedMemory` for this conversation. Only triggers when the message
 * references an SO number that is NOT the conversation's currently-active
 * SO — otherwise every first mention of the current SO would pointlessly
 * re-resolve.
 */
export function shouldInvalidateOnMessage(
    text: string | null | undefined,
    activeSo: string | null | undefined,
): boolean {
    if (!text) return false;
    const matches = text.match(TECH_REPAIR_SO_REGEX);
    if (!matches || matches.length === 0) return false;
    return matches.some((so) => so !== activeSo);
}
