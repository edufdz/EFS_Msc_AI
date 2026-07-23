/**
 * Fake Supabase Client
 * ====================
 * An in-memory, Supabase-compatible query builder backed by plain JSON
 * tables. The copied TechRepair agent code is UNCHANGED — it calls
 * `getSupabaseClient()` exactly as in production; the app layer (our
 * bootstrap) simply injects THIS client instead of a real one, mirroring
 * the "Core defines WHAT, App provides HOW" architecture of pulpoo-final.
 *
 * Supports the exact query surface used by the copied code:
 *   .from(t).select(cols, {count, head}) .eq .neq .in .is .gte .lte .gt .lt
 *   .like .ilike .or("a.eq.x,b.eq.y") .not(col,'is',null)
 *   .not(col,'in','(a,b)') .order .limit .range .single .maybeSingle
 *   .insert(...).select().single()  .update(...).eq(...)  .upsert(..., {onConflict})
 *   .delete().eq(...)   client.rpc(name, args)
 *
 * Every mutation is recorded in `db.mutationLog` so simulation harnesses
 * (Phase C) can inspect side effects after a conversation.
 */

export type Row = Record<string, any>;

export interface FakeDb {
    tables: Map<string, Row[]>;
    mutationLog: Array<{
        ts: string;
        table: string;
        op: "insert" | "update" | "upsert" | "delete" | "rpc";
        payload: unknown;
    }>;
}

export function createFakeDb(seed: Record<string, Row[]>): FakeDb {
    const tables = new Map<string, Row[]>();
    for (const [name, rows] of Object.entries(seed)) {
        tables.set(name, structuredClone(rows));
    }
    return { tables, mutationLog: [] };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _idCounter = 1000;
function genId(): string {
    _idCounter += 1;
    return `fake-${_idCounter.toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function getTable(db: FakeDb, name: string): Row[] {
    let t = db.tables.get(name);
    if (!t) {
        t = [];
        db.tables.set(name, t);
    }
    return t;
}

/** Column accessor with PostgREST JSON-path support ("raw_analysis->>event_type"). */
function getCol(row: Row, col: string): any {
    if (col.includes("->>")) {
        const [base, key] = col.split("->>");
        const obj = row[base!.trim()];
        return obj && typeof obj === "object" ? (obj as Row)[key!.trim()] : undefined;
    }
    return row[col];
}

function cmp(a: any, b: any): number {
    if (a === b) return 0;
    if (a === null || a === undefined) return -1;
    if (b === null || b === undefined) return 1;
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a) < String(b) ? -1 : 1;
}

function likeToRegex(pattern: string, flags: string): RegExp {
    const escaped = pattern.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp("^" + escaped.replace(/%/g, ".*").replace(/_/g, ".") + "$", flags);
}

type Predicate = (row: Row) => boolean;

/** Parse a PostgREST-style `.or()` filter: "col.eq.val,col2.ilike.%x%,col3.is.null" */
function parseOrFilter(filter: string): Predicate {
    const parts = filter.split(",").map((clause) => {
        const m = clause.match(/^([^.]+)\.(eq|neq|ilike|like|is|gt|gte|lt|lte)\.(.*)$/);
        if (!m) return () => false;
        const [, col, op, rawVal] = m;
        const val = rawVal === "null" ? null : rawVal;
        return (row: Row): boolean => {
            const v = getCol(row, col!);
            switch (op) {
                case "eq": return String(v) === String(val) && v !== null && v !== undefined;
                case "neq": return String(v) !== String(val);
                case "is": return val === null ? v === null || v === undefined : String(v) === String(val);
                case "ilike": return typeof v === "string" && likeToRegex(String(val), "i").test(v);
                case "like": return typeof v === "string" && likeToRegex(String(val), "").test(v);
                case "gt": return cmp(v, val) > 0;
                case "gte": return cmp(v, val) >= 0;
                case "lt": return cmp(v, val) < 0;
                case "lte": return cmp(v, val) <= 0;
                default: return false;
            }
        };
    });
    return (row) => parts.some((p) => p(row));
}

// ---------------------------------------------------------------------------
// Query builder
// ---------------------------------------------------------------------------

interface QueryResult {
    data: any;
    error: { message: string; code?: string } | null;
    count: number | null;
    status: number;
    statusText: string;
}

class FakeQueryBuilder implements PromiseLike<QueryResult> {
    private predicates: Predicate[] = [];
    private orderings: Array<{ col: string; ascending: boolean }> = [];
    private limitN: number | null = null;
    private rangeFrom: number | null = null;
    private rangeTo: number | null = null;
    private mode: "select" | "insert" | "update" | "upsert" | "delete" = "select";
    private mutationPayload: Row | Row[] | null = null;
    private upsertOnConflict: string | null = null;
    private wantCount: "exact" | null = null;
    private headOnly = false;
    private wantRows = false; // .select() chained after a mutation
    private singleMode: "single" | "maybeSingle" | null = null;

    constructor(
        private db: FakeDb,
        private tableName: string,
    ) {}

    // ---- verbs ----
    select(_cols?: string, opts?: { count?: "exact" | "planned" | "estimated"; head?: boolean }): this {
        if (this.mode !== "select") this.wantRows = true;
        if (opts?.count) this.wantCount = "exact";
        if (opts?.head) this.headOnly = true;
        return this;
    }

    insert(payload: Row | Row[]): this {
        this.mode = "insert";
        this.mutationPayload = payload;
        return this;
    }

    update(payload: Row): this {
        this.mode = "update";
        this.mutationPayload = payload;
        return this;
    }

    upsert(payload: Row | Row[], opts?: { onConflict?: string; ignoreDuplicates?: boolean }): this {
        this.mode = "upsert";
        this.mutationPayload = payload;
        this.upsertOnConflict = opts?.onConflict ?? null;
        return this;
    }

    delete(): this {
        this.mode = "delete";
        return this;
    }

    // ---- filters ----
    eq(col: string, val: any): this {
        this.predicates.push((r) => getCol(r, col) !== null && getCol(r, col) !== undefined && String(getCol(r, col)) === String(val));
        return this;
    }
    neq(col: string, val: any): this {
        this.predicates.push((r) => String(getCol(r, col)) !== String(val));
        return this;
    }
    in(col: string, vals: any[]): this {
        const set = new Set(vals.map(String));
        this.predicates.push((r) => set.has(String(getCol(r, col))));
        return this;
    }
    is(col: string, val: any): this {
        this.predicates.push((r) => (val === null ? getCol(r, col) === null || getCol(r, col) === undefined : getCol(r, col) === val));
        return this;
    }
    gte(col: string, val: any): this { this.predicates.push((r) => cmp(getCol(r, col), val) >= 0); return this; }
    lte(col: string, val: any): this { this.predicates.push((r) => cmp(getCol(r, col), val) <= 0); return this; }
    gt(col: string, val: any): this { this.predicates.push((r) => cmp(getCol(r, col), val) > 0); return this; }
    lt(col: string, val: any): this { this.predicates.push((r) => cmp(getCol(r, col), val) < 0); return this; }
    like(col: string, pattern: string): this {
        this.predicates.push((r) => typeof getCol(r, col) === "string" && likeToRegex(pattern, "").test(getCol(r, col)));
        return this;
    }
    ilike(col: string, pattern: string): this {
        this.predicates.push((r) => typeof getCol(r, col) === "string" && likeToRegex(pattern, "i").test(getCol(r, col)));
        return this;
    }
    or(filter: string): this {
        this.predicates.push(parseOrFilter(filter));
        return this;
    }
    /** .not(col, 'is', null) | .not(col, 'in', '(a,b)') | .not(col, 'eq', v) */
    not(col: string, op: string, val: any): this {
        if (op === "is") {
            this.predicates.push((r) => (val === null ? getCol(r, col) !== null && getCol(r, col) !== undefined : getCol(r, col) !== val));
        } else if (op === "in") {
            const list = String(val).replace(/^\(/, "").replace(/\)$/, "").split(",").map((s) => s.trim());
            const set = new Set(list);
            this.predicates.push((r) => !set.has(String(getCol(r, col))));
        } else if (op === "eq") {
            this.predicates.push((r) => String(getCol(r, col)) !== String(val));
        } else {
            this.predicates.push(() => true);
        }
        return this;
    }

    // ---- modifiers ----
    order(col: string, opts?: { ascending?: boolean; nullsFirst?: boolean }): this {
        this.orderings.push({ col, ascending: opts?.ascending !== false });
        return this;
    }
    limit(n: number): this { this.limitN = n; return this; }
    range(from: number, to: number): this { this.rangeFrom = from; this.rangeTo = to; return this; }
    single(): this { this.singleMode = "single"; return this; }
    maybeSingle(): this { this.singleMode = "maybeSingle"; return this; }

    // ---- execution ----
    private matchRows(rows: Row[]): Row[] {
        return rows.filter((r) => this.predicates.every((p) => p(r)));
    }

    private execute(): QueryResult {
        const table = getTable(this.db, this.tableName);
        const log = (op: "insert" | "update" | "upsert" | "delete", payload: unknown) =>
            this.db.mutationLog.push({ ts: new Date().toISOString(), table: this.tableName, op, payload: structuredClone(payload) as unknown });

        let resultRows: Row[] = [];

        if (this.mode === "select") {
            resultRows = this.matchRows(table);
            for (const { col, ascending } of [...this.orderings].reverse()) {
                resultRows = [...resultRows].sort((a, b) => (ascending ? cmp(a[col], b[col]) : cmp(b[col], a[col])));
            }
            const count = this.wantCount ? resultRows.length : null;
            if (this.rangeFrom !== null && this.rangeTo !== null) {
                resultRows = resultRows.slice(this.rangeFrom, this.rangeTo + 1);
            }
            if (this.limitN !== null) resultRows = resultRows.slice(0, this.limitN);
            if (this.headOnly) {
                return { data: null, error: null, count, status: 200, statusText: "OK" };
            }
            return this.finishSelect(resultRows, count);
        }

        if (this.mode === "insert") {
            const payloadRows = Array.isArray(this.mutationPayload) ? this.mutationPayload : [this.mutationPayload!];
            for (const p of payloadRows) {
                const row: Row = { id: genId(), created_at: new Date().toISOString(), ...structuredClone(p) };
                table.push(row);
                resultRows.push(row);
            }
            log("insert", payloadRows);
            return this.finishSelect(resultRows, null);
        }

        if (this.mode === "update") {
            const matched = this.matchRows(table);
            for (const row of matched) Object.assign(row, structuredClone(this.mutationPayload));
            resultRows = matched;
            log("update", { where: "predicates", set: this.mutationPayload, matched: matched.length });
            return this.finishSelect(resultRows, null);
        }

        if (this.mode === "upsert") {
            const payloadRows = Array.isArray(this.mutationPayload) ? this.mutationPayload : [this.mutationPayload!];
            const conflictCols = (this.upsertOnConflict ?? "id").split(",").map((s) => s.trim());
            for (const p of payloadRows) {
                const existing = table.find((r) => conflictCols.every((c) => String(r[c]) === String((p as Row)[c])));
                if (existing) {
                    Object.assign(existing, structuredClone(p));
                    resultRows.push(existing);
                } else {
                    const row: Row = { id: genId(), created_at: new Date().toISOString(), ...structuredClone(p) };
                    table.push(row);
                    resultRows.push(row);
                }
            }
            log("upsert", payloadRows);
            return this.finishSelect(resultRows, null);
        }

        // delete
        const toDelete = new Set(this.matchRows(table));
        const remaining = table.filter((r) => !toDelete.has(r));
        this.db.tables.set(this.tableName, remaining);
        log("delete", { deleted: toDelete.size });
        return this.finishSelect([...toDelete], null);
    }

    private finishSelect(rows: Row[], count: number | null): QueryResult {
        const cloned = structuredClone(rows);
        if (this.singleMode === "single") {
            if (cloned.length === 0) {
                return {
                    data: null,
                    error: { message: "JSON object requested, multiple (or no) rows returned", code: "PGRST116" },
                    count,
                    status: 406,
                    statusText: "Not Acceptable",
                };
            }
            return { data: cloned[0], error: null, count, status: 200, statusText: "OK" };
        }
        if (this.singleMode === "maybeSingle") {
            return { data: cloned[0] ?? null, error: null, count, status: 200, statusText: "OK" };
        }
        return { data: cloned, error: null, count, status: 200, statusText: "OK" };
    }

    then<TResult1 = QueryResult, TResult2 = never>(
        onfulfilled?: ((value: QueryResult) => TResult1 | PromiseLike<TResult1>) | null,
        onrejected?: ((reason: any) => TResult2 | PromiseLike<TResult2>) | null,
    ): PromiseLike<TResult1 | TResult2> {
        try {
            const result = this.execute();
            return Promise.resolve(result).then(onfulfilled, onrejected);
        } catch (err) {
            const failure: QueryResult = {
                data: null,
                error: { message: err instanceof Error ? err.message : String(err) },
                count: null,
                status: 500,
                statusText: "Internal Error",
            };
            return Promise.resolve(failure).then(onfulfilled, onrejected);
        }
    }
}

// ---------------------------------------------------------------------------
// RPC handlers (mirror the Postgres functions used by the copied code)
// ---------------------------------------------------------------------------

function handleRpc(db: FakeDb, fn: string, args: Record<string, any>): { data: any; error: { message: string } | null } {
    db.mutationLog.push({ ts: new Date().toISOString(), table: `rpc:${fn}`, op: "rpc", payload: structuredClone(args) });

    if (fn === "increment_interaction_count") {
        const rows = getTable(db, "customer_memory");
        const row = rows.find((r) => String(r.phone) === String(args.p_phone));
        if (row) {
            row.interaction_count = (row.interaction_count ?? 0) + 1;
            if (args.p_last_topic) row.last_topic = args.p_last_topic;
            if (args.p_last_seen_at) row.last_seen_at = args.p_last_seen_at;
            row.updated_at = new Date().toISOString();
        }
        return { data: null, error: null };
    }

    if (fn === "update_frustration_index") {
        const rows = getTable(db, "customer_memory");
        const row = rows.find((r) => String(r.phone) === String(args.p_phone));
        if (row) {
            // Moving average like the real Postgres fn: 70% history, 30% new signal.
            // sentiment_score 1-5 → frustration contribution 10..0
            const signal = Math.max(0, Math.min(10, (5 - (args.p_sentiment_score ?? 3)) * 2.5));
            const prev = typeof row.frustration_index === "number" ? row.frustration_index : 0;
            row.frustration_index = Math.round((prev * 0.7 + signal * 0.3) * 100) / 100;
            row.last_sentiment = args.p_last_sentiment ?? row.last_sentiment;
            row.updated_at = new Date().toISOString();
        }
        return { data: null, error: null };
    }

    if (fn === "append_escalation_history") {
        const rows = getTable(db, "escalated_tasks");
        const row = rows.find((r) => String(r.id) === String(args.p_task_id));
        if (row) {
            const history = Array.isArray(row.escalation_history) ? row.escalation_history : [];
            history.push(args.p_entry);
            row.escalation_history = history;
            row.updated_at = new Date().toISOString();
        }
        return { data: null, error: null };
    }

    return { data: null, error: { message: `Unknown RPC function: ${fn}` } };
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export interface FakeSupabaseClient {
    from(table: string): FakeQueryBuilder;
    rpc(fn: string, args?: Record<string, any>): Promise<{ data: any; error: { message: string } | null }>;
    /** Handle to the underlying store, for harness inspection & seeding. */
    __db: FakeDb;
}

export function createFakeSupabaseClient(db: FakeDb): FakeSupabaseClient {
    return {
        from(table: string) {
            return new FakeQueryBuilder(db, table);
        },
        rpc(fn: string, args: Record<string, any> = {}) {
            return Promise.resolve(handleRpc(db, fn, args));
        },
        __db: db,
    };
}
