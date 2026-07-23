/**
 * Sync router — dispatches a status-change row to the correct pipeline's
 * status_changes table.
 *
 * Used by the GSPN sync handler in `routes/dashboard.ts` (W1 Task 7).
 * Each detected status change is partitioned by `service_type` and the
 * resulting per-pipeline batches are upserted via this function.
 *
 * On NULL or 'other' service_type, we log a `lane_decision` row with
 * decision='unknown' and refuse to write — better to drop one event than
 * to write to the wrong table.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { logLaneDecision } from "./internal";

/** The shape of a row going into d2d_status_changes / carry_in_status_changes. */
export interface StatusChangeRow {
    service_order_id: string | null;
    svc_order_no: string;
    old_status?: string | null;
    new_status: string;
    changed_at: string;
    customer_phone?: string | null;
    customer_name?: string | null;
    detected_via?: string;
    event_type?: string;
    processed?: boolean;
    template_triggered?: string | null;
    time_in_previous_status_hours?: number | null;
    [key: string]: unknown;
}

export interface SyncRouteResult {
    written: boolean;
    target_table: "d2d_status_changes" | "carry_in_status_changes" | null;
    error?: string;
}

/** Result of a bulk batch route. Per-partition counts so callers can log
 *  accurately ("Logged X, deduped Y, failed Z") instead of guessing from
 *  the input length. */
export interface SyncRouteBatchResult {
    inserted: number;
    deduped: number;
    failed: number;
    /** Errors that prevented a partition from being written. Empty if
     *  every partition succeeded. */
    errors: string[];
}

/** Row shape accepted by routeStatusChangeBatch — includes the discriminator. */
export type StatusChangeRowWithType = StatusChangeRow & {
    service_type: "d2d" | "carry_in" | "other" | null | undefined;
};

export async function routeStatusChangeWrite(
    serviceType: "d2d" | "carry_in" | "other" | null | undefined,
    change: StatusChangeRow,
    supabase: SupabaseClient,
): Promise<SyncRouteResult> {
    if (serviceType !== "d2d" && serviceType !== "carry_in") {
        const reasoningSuffix =
            serviceType === "other"
                ? "service_type='other' — TechRepair-internal channel, no automated pipeline applies"
                : `service_type=${serviceType === null ? "null" : serviceType === undefined ? "undefined" : `"${String(serviceType)}"`} — order parser bug or pre-Task-1 stale data`;

        await logLaneDecision(supabase, {
            decision: "unknown",
            candidateOrders: [],
            reasoning: `sync-router skipped svc_order_no=${change.svc_order_no} — ${reasoningSuffix}`,
            source: "sync",
        });
        return {
            written: false,
            target_table: null,
            error: `unrouted service_type: ${String(serviceType)}`,
        };
    }

    const targetTable: "d2d_status_changes" | "carry_in_status_changes" =
        serviceType === "d2d" ? "d2d_status_changes" : "carry_in_status_changes";

    const { error } = await supabase.from(targetTable).upsert(change, {
        onConflict: "svc_order_no,new_status,changed_at",
        ignoreDuplicates: true,
    });

    if (error) {
        console.error(
            `[sync-router] upsert into ${targetTable} failed for ${change.svc_order_no}:`,
            error.message,
        );
        return {
            written: false,
            target_table: targetTable,
            error: error.message,
        };
    }

    return { written: true, target_table: targetTable };
}

/**
 * Bulk variant of routeStatusChangeWrite. Partitions a batch of status
 * changes by `service_type`, upserts each per-pipeline subset, and routes
 * 'other'/null rows through the single-row path so each one leaves an
 * agent_thoughts breadcrumb.
 *
 * Uses Promise.allSettled so one Postgres timeout on a partition doesn't
 * abort the others. Returns true counts (`inserted` = rows actually
 * written, `deduped` = rows that hit the *_dedup UNIQUE — these are
 * benign retries from concurrent operators or batch re-runs) so the
 * caller's log line can be accurate instead of misleading.
 */
export async function routeStatusChangeBatch(
    rows: StatusChangeRowWithType[],
    supabase: SupabaseClient,
): Promise<SyncRouteBatchResult> {
    const partition = (st: "d2d" | "carry_in") =>
        rows
            .filter((r) => r.service_type === st)
            .map(({ service_type: _service_type, ...rest }) => rest);

    const d2dRows = partition("d2d");
    const carryInRows = partition("carry_in");
    const unrouted = rows.filter(
        (r) => r.service_type !== "d2d" && r.service_type !== "carry_in",
    );

    const upsertOpts = {
        onConflict: "svc_order_no,new_status,changed_at",
        ignoreDuplicates: true,
    } as const;

    type PartitionResult = { table: string; attempted: number; inserted: number; error?: string };

    const writePartition = async (
        table: "d2d_status_changes" | "carry_in_status_changes",
        partitionRows: StatusChangeRow[],
    ): Promise<PartitionResult> => {
        if (partitionRows.length === 0) {
            return { table, attempted: 0, inserted: 0 };
        }
        const { data, error } = await supabase
            .from(table)
            .upsert(partitionRows, upsertOpts)
            .select();
        if (error) {
            return {
                table,
                attempted: partitionRows.length,
                inserted: 0,
                error: error.message,
            };
        }
        return {
            table,
            attempted: partitionRows.length,
            inserted: data?.length ?? 0,
        };
    };

    const settled = await Promise.allSettled([
        writePartition("d2d_status_changes", d2dRows),
        writePartition("carry_in_status_changes", carryInRows),
    ]);

    let inserted = 0;
    let deduped = 0;
    let failed = 0;
    const errors: string[] = [];

    for (const r of settled) {
        if (r.status === "rejected") {
            failed += 1;
            errors.push(String(r.reason));
            continue;
        }
        const part = r.value;
        if (part.error) {
            failed += part.attempted;
            errors.push(`${part.table}: ${part.error}`);
            continue;
        }
        inserted += part.inserted;
        deduped += part.attempted - part.inserted;
    }

    // 'other'/null rows: each goes through the single-row helper so a
    // lane_decision audit is recorded. These never write to a
    // status_changes table; they count as 'deduped' from the caller's
    // perspective (intentionally skipped).
    const unroutedResults = await Promise.allSettled(
        unrouted.map((row) => {
            const { service_type: serviceType, ...rest } = row;
            return routeStatusChangeWrite(serviceType, rest, supabase);
        }),
    );
    for (const r of unroutedResults) {
        if (r.status === "rejected") {
            failed += 1;
            errors.push(`unrouted row: ${String(r.reason)}`);
        } else {
            deduped += 1;
        }
    }

    return { inserted, deduped, failed, errors };
}
