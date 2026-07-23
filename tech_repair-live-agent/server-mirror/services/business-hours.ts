/**
 * Business Hours Service
 * ======================
 * Mexico City timezone business hours enforcement for outbound operations.
 * Uses Intl.DateTimeFormat for correct timezone math regardless of server timezone.
 */

const MEXICO_TZ = 'America/Mexico_City'
const BUSINESS_HOURS = { start: 10, end: 19 } // 10 AM - 7 PM

// Shared formatter — created once, reused for every call
const mexicoFormatter = new Intl.DateTimeFormat('en-US', {
    timeZone: MEXICO_TZ,
    hour: 'numeric',
    hour12: false,
    weekday: 'short',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    minute: '2-digit',
})

/**
 * Extract Mexico City hour and weekday from any Date, regardless of server timezone.
 */
function getMexicoParts(date: Date): { hour: number; minute: number; day: number } {
    const parts = mexicoFormatter.formatToParts(date)
    const get = (type: Intl.DateTimeFormatPartTypes) =>
        parts.find((p) => p.type === type)?.value ?? ''

    const hour = parseInt(get('hour'), 10)
    const minute = parseInt(get('minute'), 10)

    // Map weekday abbreviation to JS day number (0=Sun, 6=Sat)
    const dayMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }
    const day = dayMap[get('weekday')] ?? 0

    return { hour, minute, day }
}

/**
 * Check if a time is within Mexico City business hours (Mon-Sat 10AM-7PM)
 */
export function isWithinBusinessHours(date: Date): boolean {
    const { hour, day } = getMexicoParts(date)
    if (day === 0) return false // Sunday only
    return hour >= BUSINESS_HOURS.start && hour < BUSINESS_HOURS.end
}

/**
 * Get the next available business hours window.
 * Returns a Date with the correct UTC timestamp for the next 10 AM Mexico City.
 */
export function getNextBusinessWindow(from: Date = new Date()): Date {
    if (isWithinBusinessHours(from)) return from

    const { hour, day } = getMexicoParts(from)

    // How many Mexico-City days forward to reach the next business morning.
    let daysToAdd = 0
    if (day === 0) {
        daysToAdd = 1 // Sunday → Monday
    } else if (hour >= BUSINESS_HOURS.end) {
        daysToAdd = day === 6 ? 2 : 1 // after hours → next day (Mon if Saturday)
    }
    // else: before hours on a business day → same MX day (daysToAdd = 0)

    // Shift the *instant* by whole days. Mexico City has no DST (abolished
    // 2022), so +24h advances the MX wall-clock date by exactly one day.
    // We must NOT use `result.setUTCDate(getUTCDate() + daysToAdd)`: in the
    // evening the UTC date is already a day ahead of the MX date (MX is
    // UTC-6), so that double-counts and lands a full day late.
    const onTargetDay = new Date(from.getTime() + daysToAdd * 86_400_000)
    return snapToBusinessStart(onTargetDay)
}

/**
 * Snap an instant to BUSINESS_HOURS.start o'clock Mexico City on the *same
 * MX day*. Shifts by the MX-hour delta (re-derived from the timezone
 * formatter) so it's correct regardless of server timezone — and since the
 * shift only moves between hours-of-day, never across MX midnight, it stays
 * on the same MX calendar day.
 */
function snapToBusinessStart(d: Date): Date {
    const { hour } = getMexicoParts(d)
    const result = new Date(d.getTime() + (BUSINESS_HOURS.start - hour) * 3_600_000)
    // MX is a whole-hour offset, so MX minutes/seconds == UTC minutes/seconds.
    result.setUTCMinutes(0, 0, 0)
    return result
}

/**
 * Add N business hours to a start instant, counting only time inside the
 * business window (Mon-Sat 10AM-7PM Mexico City). Nights, Sundays and
 * after-hours are paused — they don't consume the budget.
 *
 * Used to compute escalation SLA deadlines so a case opened at 6PM Friday
 * isn't "overdue" overnight or over the weekend; the clock resumes at the
 * next business window.
 */
export function addBusinessHours(from: Date, hours: number): Date {
    // Snap the start into the business window (no-op if already inside).
    let cursor = getNextBusinessWindow(from)
    let remainingMs = hours * 3_600_000

    // Walk forward one business day at a time, draining the budget.
    while (remainingMs > 0) {
        const { hour, minute } = getMexicoParts(cursor)
        // Minutes left until the window closes (BUSINESS_HOURS.end o'clock).
        const msUntilClose = ((BUSINESS_HOURS.end - hour) * 60 - minute) * 60_000

        if (remainingMs <= msUntilClose) {
            return new Date(cursor.getTime() + remainingMs)
        }

        // Consume the rest of today's window and jump to the next one.
        remainingMs -= msUntilClose
        const afterClose = new Date(cursor.getTime() + msUntilClose + 60_000)
        cursor = getNextBusinessWindow(afterClose)
    }

    return cursor
}

/**
 * Calculate when a job should execute based on business hours.
 */
export function calculateExecutionTime(scheduledFor?: string): {
    executeAt: Date
    immediate: boolean
    reason: 'immediate' | 'scheduled' | 'outside_hours'
} {
    const now = new Date()

    if (scheduledFor) {
        const executeAt = new Date(scheduledFor)
        if (executeAt.getTime() <= now.getTime()) {
            if (isWithinBusinessHours(now)) {
                return { executeAt: now, immediate: true, reason: 'immediate' }
            }
            return { executeAt: getNextBusinessWindow(now), immediate: false, reason: 'outside_hours' }
        }
        return { executeAt, immediate: false, reason: 'scheduled' }
    }

    if (isWithinBusinessHours(now)) {
        return { executeAt: now, immediate: true, reason: 'immediate' }
    }
    return { executeAt: getNextBusinessWindow(now), immediate: false, reason: 'outside_hours' }
}

/**
 * Get business hours info for API response.
 */
export function getBusinessHoursInfo(): {
    timezone: string
    start: string
    end: string
    isOpen: boolean
    nextOpen?: string
} {
    const now = new Date()
    const isOpen = isWithinBusinessHours(now)

    return {
        timezone: MEXICO_TZ,
        start: `${BUSINESS_HOURS.start}:00`,
        end: `${BUSINESS_HOURS.end}:00`,
        isOpen,
        ...(!isOpen && { nextOpen: getNextBusinessWindow(now).toISOString() }),
    }
}
