/**
 * Phone Normalization
 * ===================
 * Converts various phone formats to canonical E.164 (+52... for MX, +1... for US).
 * Used as the consistent user_id key for both SQL memory and mem0 vector store.
 */

/**
 * Normalize a phone number to E.164 format.
 * Returns null if the input can't be reliably formatted.
 *
 * Examples:
 *   "5512345678"      → "+525512345678"   (10-digit MX)
 *   "525512345678"    → "+525512345678"   (12-digit with MX prefix)
 *   "+525512345678"   → "+525512345678"   (already E.164)
 *   "15550001234"     → "+15550001234"    (US with country code)
 *   "abc"             → null
 */
export function normalizePhone(raw: string): string | null {
    const digits = raw.replace(/\D/g, "");

    // Already E.164 (starts with +, has enough digits)
    if (raw.startsWith("+") && digits.length >= 10) return `+${digits}`;

    // 10-digit Mexican number (no country code)
    if (digits.length === 10) return `+52${digits}`;

    // 12-digit with Mexican country code (52XXXXXXXXXX)
    if (digits.length === 12 && digits.startsWith("52")) return `+${digits}`;

    // 11-digit US number with country code (1XXXXXXXXXX)
    if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;

    return null;
}

/**
 * Expand a phone number into all plausible storage variants for cross-table
 * matching. `customer_memory.phone` and `whatsapp_conversations.phone_number`
 * sometimes carry the E.164 form ("+5219711421053") and sometimes the bare
 * 10-digit form ("4611024878"). `service_orders.cust_mobile_phone` is
 * typically bare. Generate all plausible variants so a join on each table
 * finds a hit regardless of which format the caller typed.
 *
 * Intended use: `WHERE phone_col = ANY($1)` with the output as the array
 * parameter. If the callsite needs whitespace/dash tolerance on the column
 * itself, normalize the LHS inline: `regexp_replace(col, '[^0-9+]', '', 'g')`.
 */
export function expandPhoneVariants(phone: string): string[] {
    const trimmed = phone.trim();
    const digitsOnly = trimmed.replace(/\D/g, "");
    const variants = new Set<string>();
    variants.add(trimmed);
    variants.add(digitsOnly);
    if (digitsOnly.startsWith("521") && digitsOnly.length === 13) {
        variants.add(digitsOnly.slice(3));
        variants.add("+" + digitsOnly);
    } else if (digitsOnly.startsWith("52") && digitsOnly.length === 12) {
        variants.add(digitsOnly.slice(2));
        variants.add("+" + digitsOnly);
    } else if (digitsOnly.length === 10) {
        variants.add("+52" + digitsOnly);
        variants.add("+521" + digitsOnly);
        variants.add("52" + digitsOnly);
        variants.add("521" + digitsOnly);
    }
    return Array.from(variants);
}
