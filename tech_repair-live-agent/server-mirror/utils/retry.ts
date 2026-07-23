/**
 * Centralized retry utility with exponential backoff.
 * All services MUST use this module instead of implementing their own retry logic.
 *
 * @module utils/retry
 */

export interface RetryOptions {
    /** Maximum number of attempts (default: 3) */
    maxAttempts?: number;
    /** Initial delay in ms (default: 1000) */
    initialDelayMs?: number;
    /** Maximum delay in ms (default: 10000) */
    maxDelayMs?: number;
    /** Backoff multiplier (default: 2) */
    multiplier?: number;
    /** Whether to add jitter to delay (default: true) */
    jitter?: boolean;
    /** Predicate: should retry on this error? (default: always retry) */
    retryIf?: (error: unknown) => boolean;
    /** Called before each retry with attempt info */
    onRetry?: (error: unknown, attempt: number, delayMs: number) => void;
    /** AbortSignal to cancel retries */
    signal?: AbortSignal;
}

const DEFAULT_OPTIONS: Required<Omit<RetryOptions, 'retryIf' | 'onRetry' | 'signal'>> = {
    maxAttempts: 3,
    initialDelayMs: 1000,
    maxDelayMs: 10_000,
    multiplier: 2,
    jitter: true,
};

/**
 * Execute an async function with exponential backoff retry.
 *
 * @example
 * ```ts
 * const result = await withRetry(
 *   () => gspnClient.getServiceOrders(),
 *   {
 *     maxAttempts: 5,
 *     initialDelayMs: 2000,
 *     retryIf: (err) => err instanceof TimeoutError || err instanceof RateLimitError,
 *   }
 * );
 * ```
 */
export async function withRetry<T>(
    fn: () => Promise<T>,
    options: RetryOptions = {},
): Promise<T> {
    const opts = { ...DEFAULT_OPTIONS, ...options };
    let lastError: unknown;

    for (let attempt = 1; attempt <= opts.maxAttempts; attempt++) {
        try {
            // Check if cancelled
            if (opts.signal?.aborted) {
                throw new RetryAbortedError('Retry aborted by signal', { cause: lastError });
            }

            return await fn();
        } catch (error) {
            lastError = error;

            // Don't retry if this is the last attempt
            if (attempt >= opts.maxAttempts) {
                break;
            }

            // Don't retry if predicate says no
            if (opts.retryIf && !opts.retryIf(error)) {
                break;
            }

            // Calculate delay with exponential backoff
            let delayMs = Math.min(
                opts.initialDelayMs * Math.pow(opts.multiplier, attempt - 1),
                opts.maxDelayMs,
            );

            // Add jitter (±25%)
            if (opts.jitter) {
                const jitterFactor = 0.75 + Math.random() * 0.5; // 0.75 to 1.25
                delayMs = Math.round(delayMs * jitterFactor);
            }

            // Notify listener
            opts.onRetry?.(error, attempt, delayMs);

            // Wait before retry
            await sleep(delayMs, opts.signal);
        }
    }

    throw lastError;
}

/**
 * Sleep that respects AbortSignal.
 */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        if (signal?.aborted) {
            reject(new RetryAbortedError('Retry aborted by signal'));
            return;
        }

        const timer = setTimeout(resolve, ms);

        signal?.addEventListener('abort', () => {
            clearTimeout(timer);
            reject(new RetryAbortedError('Retry aborted by signal'));
        }, { once: true });
    });
}

/**
 * Error thrown when retry is cancelled via AbortSignal.
 */
export class RetryAbortedError extends Error {
    constructor(message: string, options?: ErrorOptions) {
        super(message, options);
        this.name = 'RetryAbortedError';
    }
}
