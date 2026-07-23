/**
 * Style-Guide Post-Processor (D12)
 * ===============================
 * Runs AFTER node-level content generation and BEFORE sendMessage.
 * Enforces nine voice rules derived from 130+ human-agent replies at
 * SimTech Polanco so the bot's tone matches how humans actually open a
 * conversation, acknowledge frustration, and close warmly.
 *
 * Rules (in execution order):
 *   1. greeting_suppression          — welcome template only on first outbound
 *   2. register_lock                 — tú/usted locked per conversation
 *   3. acknowledgment_prefix         — empathy line (≤10 words) on emotional cues
 *   4. length_match                  — cap for concise-intent replies (trim, no regen)
 *   5. name_sanitization             — exported separately for callers interpolating name
 *   6. no_empty_promises             — "te aviso cuando" only when a hook is active
 *   7. repetition_breaker            — caller-tracked; stub here
 *   8. ban_self_flagellation         — no "Lamentablemente / Desafortunadamente / No tengo acceso" openings
 *   9. no_reflexive_closing_question — "¿algo más...?" only after concrete resolution + non-closing inbound
 */

export type Register = "formal" | "informal" | "default_formal";

// =============================================================================
// Rule 5 — name sanitization (standalone export; used at interpolation time)
// =============================================================================

/**
 * Clean up raw customer_name strings for use in greetings.
 *
 * Returns:
 *   - "" when the name contains only non-word tokens (garbage like "-->", "|")
 *     or is unusable. Callers emit "Hola," instead of "Hola, [Name]".
 *   - "equipo de [Company]" for detected company names (ends in Servicios,
 *     S.A., SA de CV, S. de R.L., etc.).
 *   - The first token, title-cased, for normal personal names.
 */
export function sanitizeCustomerName(raw: string | null | undefined): string {
    if (!raw) return "";
    const trimmed = raw.trim();
    if (!trimmed) return "";

    // Hard reject: strings with clear non-word markers
    if (/[<>|\\/*=^]/.test(trimmed)) return "";

    // Company detection — matches the tail of the string
    const COMPANY_SUFFIX_RE =
        /\b(servicios|s\.?\s*a\.?\s*(de\s+c\.?\s*v\.?)?|s\.?\s*de\s+r\.?\s*l\.?|srl|sac)\b\.?$/i;
    if (COMPANY_SUFFIX_RE.test(trimmed)) {
        return `equipo de ${titleCaseWords(trimmed)}`;
    }

    // Split into tokens; require at least one alphabetic token
    const tokens = trimmed.split(/\s+/).filter(Boolean);
    const alphaTokens = tokens.filter((t) => /[a-záéíóúñü]/i.test(t));
    if (alphaTokens.length === 0) return "";

    // Take the first alphabetic token, title-case it
    return titleCase(alphaTokens[0]);
}

function titleCase(word: string): string {
    if (!word) return "";
    return word.charAt(0).toLocaleUpperCase("es-MX") + word.slice(1).toLocaleLowerCase("es-MX");
}

function titleCaseWords(phrase: string): string {
    return phrase
        .split(/\s+/)
        .map((w) => (w.length <= 2 ? w.toLocaleLowerCase("es-MX") : titleCase(w)))
        .join(" ")
        .trim();
}

// =============================================================================
// Rule 2 — register detection and lock
// =============================================================================

// JS `\b` is ASCII-only, so "tú" gets split at the ú. Use lookarounds on
// Unicode letters (requires the `u` flag) to correctly detect word edges
// around accented Spanish characters.
const B = "(?<!\\p{L})"; // left boundary — prev char is not a Unicode letter
const E = "(?!\\p{L})"; // right boundary — next char is not a Unicode letter

const FORMAL_MARKERS = new RegExp(
    `${B}(usted|ustedes|acuda|env[ií]e|permítame|dígame|tenga)${E}`,
    "iu",
);
const INFORMAL_MARKERS = new RegExp(
    `${B}(t[úu]|tuyo|tuya|tuyas|tuyos|contigo|avísame|dímelo)${E}`,
    "iu",
);

/**
 * Classify the register of the first inbound message. Defaults to formal
 * when ambiguous, because Mexican service-center tone leans formal by default.
 */
export function detectRegister(inbound: string | null | undefined): Register {
    if (!inbound) return "default_formal";
    if (FORMAL_MARKERS.test(inbound)) return "formal";
    if (INFORMAL_MARKERS.test(inbound)) return "informal";
    return "default_formal";
}

function W(word: string): RegExp {
    return new RegExp(`${B}${word}${E}`, "giu");
}

const INFORMAL_TO_FORMAL: Array<[RegExp, string]> = [
    [W("tú"), "usted"],
    [W("tu"), "su"],
    [W("tus"), "sus"],
    [W("ti"), "usted"],
    [W("tuyo"), "suyo"],
    [W("tuya"), "suya"],
    [W("contigo"), "con usted"],
];

const FORMAL_TO_INFORMAL: Array<[RegExp, string]> = [
    [W("usted"), "tú"],
    [W("suyo"), "tuyo"],
    [W("suya"), "tuya"],
    [/con usted/giu, "contigo"],
    // NOTE: "su"/"sus" is ambiguous (also 3rd-person possessive). Leave alone
    // and rely on the detector at generation time rather than post-hoc rewrite.
];

/**
 * Rewrite obvious 2nd-person pronoun mismatches to match the locked register.
 * Conservative: only swaps the safest tokens. "su"/"sus" are left alone in
 * both directions because they also serve as 3rd-person possessives (e.g.
 * "aviso a logística de su caso" — the "su" there refers to the customer's
 * case, not a formal 2nd-person address).
 */
export function lockRegister(message: string, register: Register): string {
    if (register === "formal" || register === "default_formal") {
        return INFORMAL_TO_FORMAL.reduce(
            (acc, [re, rep]) => acc.replace(re, rep),
            message,
        );
    }
    if (register === "informal") {
        return FORMAL_TO_INFORMAL.reduce(
            (acc, [re, rep]) => acc.replace(re, rep),
            message,
        );
    }
    return message;
}

// =============================================================================
// Rule 1 — greeting suppression
// =============================================================================

const WELCOME_PATTERNS: RegExp[] = [
    // The canonical GOODBYE_RESPONSE counterpart — the old multi-bullet greeting
    /¡Hola!\s*👋?\s*Bienvenido al Centro de Servicio TechRepair Polanco\.[^.!?\n]*[.!?\n]\s*/i,
    // Shorter welcome variants
    /¡Hola!\s*Bienvenido al Centro de Servicio[^.!?\n]*[.!?\n]\s*/i,
    // The bullet list that sometimes follows
    /Puedo asistirle con:\s*[-•]\s*[^\n]+\n(?:\s*[-•]\s*[^\n]+\n?)*/i,
];

function stripWelcome(message: string): string {
    let out = message;
    for (const pat of WELCOME_PATTERNS) out = out.replace(pat, "");
    return out.trimStart();
}

// =============================================================================
// Rule 3 — acknowledgment prefix
// =============================================================================

interface AcknowledgmentMatch {
    prefixFormal: string;
    prefixInformal: string;
}

const ACKNOWLEDGMENT_RULES: Array<{
    test: (inbound: string) => boolean;
    match: AcknowledgmentMatch;
}> = [
    {
        test: (m) => /\b(disculpe|molestia|perdón|perdon)\b/i.test(m),
        match: {
            prefixFormal: "Para nada, con gusto le ayudo.",
            prefixInformal: "Para nada, con gusto te ayudo.",
        },
    },
    {
        test: (m) => /\b(esperando|tardado|demora|llevo\s+d[ií]as)\b/i.test(m),
        match: {
            prefixFormal: "Entiendo la espera, déjeme revisar.",
            prefixInformal: "Entiendo la espera, déjame revisar.",
        },
    },
    {
        test: (m) => /\b(urgencia|urgente|necesito\s+ya)\b/i.test(m),
        match: {
            prefixFormal: "Sé que es urgente, reviso ahora mismo.",
            prefixInformal: "Sé que es urgente, reviso ahora mismo.",
        },
    },
];

function acknowledgmentPrefix(
    inbound: string | undefined,
    register: Register,
    longWaitThankCase: boolean,
): string | null {
    if (longWaitThankCase) {
        return register === "informal"
            ? "Gracias a ti por la paciencia."
            : "Gracias a usted por la paciencia.";
    }
    if (!inbound) return null;
    for (const rule of ACKNOWLEDGMENT_RULES) {
        if (rule.test(inbound)) {
            return register === "informal"
                ? rule.match.prefixInformal
                : rule.match.prefixFormal;
        }
    }
    return null;
}

// =============================================================================
// Rule 8 — ban self-flagellation openings
// =============================================================================

const SELF_FLAGELLATION_OPENERS =
    /^(\s*)(lamentablemente|desafortunadamente|lamento\s+que|no\s+tengo\s+acceso|no\s+puedo\s+ver|en\s+mi\s+sistema\s+no)/i;

function stripSelfFlagellationOpener(message: string): string {
    // Strip only the first sentence if it opens with a banned phrase.
    if (!SELF_FLAGELLATION_OPENERS.test(message)) return message;
    const firstSentenceEnd = message.search(/[.!?\n]/);
    if (firstSentenceEnd === -1) return ""; // whole message is self-flagellation
    return message.slice(firstSentenceEnd + 1).trimStart();
}

// =============================================================================
// Rule 9 — no reflexive closing question
// =============================================================================

const CLOSING_QUESTION_RE =
    /¿\s*hay\s+algo\s+m[aá]s\s+en\s+lo\s+que\s+(pueda|puedo)\s+ayud\w*\??\s*/gi;

const CLOSING_INBOUND_RE =
    /^\s*(gracias|muchas\s+gracias|ok|listo|excelente|perfecto|enterado|vale|👍|🙏)\s*[!.]?\s*$/i;

/**
 * Remove the default closing question unless a concrete resolution happened
 * AND the last inbound was something more than a closing token.
 */
function suppressClosingQuestion(
    message: string,
    didConcreteResolution: boolean,
    lastInboundIsClosing: boolean,
): string {
    if (didConcreteResolution && !lastInboundIsClosing) {
        return message; // allowed
    }
    return message.replace(CLOSING_QUESTION_RE, "").replace(/\s+$/g, "").trimEnd();
}

// =============================================================================
// Rule 4 — length match (trim only; regeneration deferred)
// =============================================================================

const CONCISE_INTENTS = new Set([
    "order_status",
    "confirmation",
    "warranty_question",
    "delivery_logistics",
    "contact_info_request",
]);

function applyLengthCap(
    message: string,
    intent: string | undefined,
    inboundLength: number,
): string {
    if (!intent || !CONCISE_INTENTS.has(intent)) return message;
    const cap = Math.max(120, inboundLength * 3);
    if (message.length <= cap) return message;
    // Cut at last full-stop boundary within the cap
    const truncated = message.slice(0, cap);
    const lastBoundary = Math.max(
        truncated.lastIndexOf(". "),
        truncated.lastIndexOf("\n"),
    );
    return lastBoundary > cap * 0.6
        ? truncated.slice(0, lastBoundary + 1).trimEnd()
        : truncated.trimEnd();
}

// =============================================================================
// Rule 6 — no empty promises
// =============================================================================

const EMPTY_PROMISE_RE =
    /(?:te|le)\s+(aviso|notifico)\s+(?:cuando|en\s+cuanto)[^.!?\n]*[.!?\n]/gi;

const AWAITER_USER_FALLBACK_FORMAL =
    "Si gusta revisarlo más tarde, avíseme y consulto nuevamente.";
const AWAITER_USER_FALLBACK_INFORMAL =
    "Si quieres revisarlo más tarde, avísame y consulto de nuevo.";

function enforcePromiseHooks(
    message: string,
    availableHooks: Set<string>,
    register: Register,
): string {
    if (availableHooks.has("any")) return message;
    if (!EMPTY_PROMISE_RE.test(message)) return message;
    const fallback =
        register === "informal"
            ? AWAITER_USER_FALLBACK_INFORMAL
            : AWAITER_USER_FALLBACK_FORMAL;
    return message.replace(EMPTY_PROMISE_RE, fallback + " ").trim();
}

// =============================================================================
// Rule 7 — repetition breaker (caller-tracked)
// =============================================================================

export interface RepetitionSignal {
    shouldEscalate: boolean;
    reason?: "repeated_lookup_failure";
}

/**
 * Callers track (intent, outcome) tuples per conversation in a short window
 * and pass the count here. If the same pair has fired 3 times in the last
 * 5 minutes, this signals the logic to escalate instead of repeating the
 * canned "please give me your order number" reply.
 */
export function detectRepetitionBreak(
    sameOutcomeCountInWindow: number,
): RepetitionSignal {
    if (sameOutcomeCountInWindow >= 3) {
        return { shouldEscalate: true, reason: "repeated_lookup_failure" };
    }
    return { shouldEscalate: false };
}

// =============================================================================
// Orchestrator
// =============================================================================

export interface StyleContext {
    /** True when this will be the first outbound message of the conversation. */
    isFirstOutbound: boolean;
    /** Locked register (from state.metadata.register). */
    register: Register;
    /** The customer's current inbound message — used by rules 3 and 4. */
    inboundMessage?: string;
    /** Current intent bucket — used by rule 4. */
    intent?: string;
    /** True when >1h has passed since the last outbound message. Drives rule 3's "thank for patience" branch. */
    longWaitThankCase?: boolean;
    /** Hooks that actually fire proactive follow-ups (e.g. "d2d_notifier", "cost_followup"). "any" disables rule 6. */
    availablePromiseHooks?: Set<string>;
    /** True when the last inbound was a closing token (gracias, ok, etc.). Used by rule 9. */
    lastInboundIsClosing?: boolean;
    /** True when the node produced a concrete resolution (answered status, gave contact, etc.). Used by rule 9. */
    didConcreteResolution?: boolean;
}

/**
 * Apply the full D12 style guide to a bot-generated message.
 * Rules fire in order; later rules see the output of earlier ones.
 */
export function applyStyleGuide(message: string, ctx: StyleContext): string {
    let out = message;

    // 8 first — a banned opener may be cheaper to strip before we evaluate
    // length (so the effective cap applies to the real content).
    out = stripSelfFlagellationOpener(out);

    // 1 — greeting suppression
    if (!ctx.isFirstOutbound) out = stripWelcome(out);

    // 3 — acknowledgment prefix
    const ack = acknowledgmentPrefix(
        ctx.inboundMessage,
        ctx.register,
        ctx.longWaitThankCase ?? false,
    );
    if (ack) out = `${ack} ${out}`.trimStart();

    // 6 — promise hook enforcement
    out = enforcePromiseHooks(
        out,
        ctx.availablePromiseHooks ?? new Set(),
        ctx.register,
    );

    // 2 — register lock
    out = lockRegister(out, ctx.register);

    // 9 — suppress reflexive closing question
    out = suppressClosingQuestion(
        out,
        ctx.didConcreteResolution ?? false,
        ctx.lastInboundIsClosing ?? false,
    );

    // 4 — length cap (last, so the measurement reflects final content)
    out = applyLengthCap(
        out,
        ctx.intent,
        (ctx.inboundMessage ?? "").length,
    );

    return out.trim();
}
