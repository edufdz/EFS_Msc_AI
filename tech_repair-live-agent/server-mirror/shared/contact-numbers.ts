/**
 * Contact Numbers — single source of truth for the two customer-facing lines
 * =========================================================================
 * TechRepair-next surfaces two phone numbers to customers and they must NOT be
 * conflated:
 *
 *   agentPhone — the AI self-service line (the inbound voice agent / "bought"
 *                Twilio number). Hand this out as a *fallback for status
 *                checks* — "another way to look up your order". It reaches a
 *                bot, so it must NOT be the number a frustrated customer is
 *                pushed toward.
 *
 *   storePhone — the real store's direct line. Reaches a person. Reserve it
 *                for frustration, explicit human requests, and cases the
 *                agents genuinely cannot resolve.
 *
 * Source of truth is the `app_config` row `contact_numbers` (JSONB, editable
 * live within the 30s cache via getAppConfig). Any field that is missing,
 * blank, or not E.164-shaped falls back to env (SUPPORT_PHONE / STORE_DIRECT_
 * PHONE), so this works on day one with zero DB rows. Never throws — a bad DB
 * value degrades to the env value rather than breaking a customer reply.
 */

import { getAppConfig } from "./app-config";

export interface ContactNumbers {
    /** AI self-service line (inbound voice / bought number) — status fallback. */
    agentPhone: string;
    /** Real human store line — frustration / explicit-human / unresolved. */
    storePhone: string;
}

/** Shape of the `contact_numbers` app_config value (all fields optional). */
interface ContactNumbersConfig {
    agentPhone?: string | null;
    storePhone?: string | null;
}

const APP_CONFIG_KEY = "contact_numbers";

/** Same E.164-ish shape the inbound config enforces on STORE_DIRECT_PHONE. */
const E164_RE = /^\+?\d{10,15}$/;

/** Hard default for the agent line — the historical SUPPORT_PHONE default. */
const DEFAULT_AGENT_PHONE = "+525588974249";

function isValidPhone(value: unknown): value is string {
    return typeof value === "string" && E164_RE.test(value.trim());
}

/** Pick the first E.164-valid candidate, else undefined. */
function firstValid(
    ...candidates: Array<string | null | undefined>
): string | undefined {
    for (const candidate of candidates) {
        if (isValidPhone(candidate)) return candidate.trim();
    }
    return undefined;
}

/**
 * Resolve both customer-facing numbers. DB value wins per-field; missing /
 * blank / malformed fields fall back to env, then to a hard default. If the
 * store line cannot be resolved at all, it degrades to the agent line (so copy
 * never renders an empty number) and logs a warning — a misconfigured store
 * number is an ops problem to surface, not a reason to crash a reply.
 */
export async function getContactNumbers(): Promise<ContactNumbers> {
    const dbConfig = await getAppConfig<ContactNumbersConfig>(APP_CONFIG_KEY, {});

    const agentPhone =
        firstValid(
            dbConfig?.agentPhone,
            process.env.SUPPORT_PHONE,
            DEFAULT_AGENT_PHONE,
        ) ?? DEFAULT_AGENT_PHONE;

    const storePhone = firstValid(
        dbConfig?.storePhone,
        process.env.STORE_DIRECT_PHONE,
    );

    if (!storePhone) {
        console.warn(
            "[contact-numbers] No valid storePhone in app_config or " +
                "STORE_DIRECT_PHONE; falling back to agentPhone. Set the real " +
                "store line to stop routing frustrated customers to the AI line.",
        );
        return { agentPhone, storePhone: agentPhone };
    }

    return { agentPhone, storePhone };
}
