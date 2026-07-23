/**
 * Order Lookup Tool
 * =================
 * Looks up service order status from Supabase.
 * Uses shared GSPN status codes for human-readable labels.
 *
 * Status-disclosure gate (W1 Task 8): after fetching the order, this
 * tool consults `service_status_policy` for the (service_type, status)
 * pair. If `proactive_status_disclosure=false` (e.g. carry_in +
 * ready_for_pickup — customer is at the SIMTECH door), every field
 * that discloses repair progress is stripped from the response BEFORE
 * the LLM ever sees it. The LLM literally cannot reveal what it
 * doesn't know — making this a hard rule, not a prompt instruction.
 */

import { requireSupabaseClient, getSupabaseClient } from "@/shared/supabase";
import { STATUS_CODE_LABELS, isOutOfWarranty } from "@/services/gspn/constants";
import { logToolInvocation } from "@/shared/supabase-logger";
import { getPolicyForServiceType } from "@/shared/service-status-policy";
import { logAgentThought } from "@/services/lane-selector";
import { getIQCDescription } from "@/data/iqc-codes";

export interface OrderLookupResult {
    found: boolean;
    svc_order_no: string;
    /**
     * Pipeline classifier. Surfaced so the status node's `order_data` lets
     * the LLM distinguish carry-in (in-store pickup) from d2d (home delivery)
     * — without it the status prompt's `service_type = "d2d"` rule is dead and
     * carry-in customers get told their device ships home. Deliberately NOT in
     * the disclosure-gate strip list below: this is a modality flag, not repair
     * progress, so it survives even when status fields are stripped.
     */
    service_type?: "d2d" | "carry_in" | "other";
    status?: string;
    status_label?: string;
    model_name?: string;
    repair_cost_mxn?: number;
    warranty_type?: string;
    req_date?: string;
    complete_date?: string;
    estimated_completion?: string;
    defect_desc?: string;
    repair_action_desc?: string;
    iris_condition_desc?: string;
    iris_symptom_desc?: string;
    iris_defect_desc?: string;
    iris_repair_desc?: string;
    /** Joined symptom-code blob from GSPN (`SymCode1..N` / `SymDesc1..N`). */
    symptom_desc?: string;
    /**
     * IQC codes extracted from {@link symptom_desc} with Mexican-Spanish
     * descriptions added. Codes recognized by TechRepair's IQC sheet have
     * `desc_es` populated; codes that match the IQC shape but aren't in
     * our table land here with `desc_es: null` (signal for the agent to
     * follow the tier-1 fallback — ask for context, then escalate).
     * Absent or empty when the order has no detectable IQC codes.
     */
    symptom_codes_enriched?: Array<{
        code: string;
        desc_en: string | null;
        desc_es: string | null;
    }>;
    error?: string;
}

/**
 * Look up a service order by order number.
 *
 * Queries the `service_orders` table in Supabase (populated by GSPN poller).
 */
export async function lookupOrder(
    svcOrderNo: string,
): Promise<OrderLookupResult> {
    const t0 = Date.now();
    let result: OrderLookupResult;

    try {
        const client = requireSupabaseClient();

        const { data, error } = await client
            .from("service_orders")
            .select("*")
            .eq("svc_order_no", svcOrderNo)
            .maybeSingle();

        if (error) {
            result = {
                found: false,
                svc_order_no: svcOrderNo,
                error: `Database error: ${error.message}`,
            };
        } else if (!data) {
            result = {
                found: false,
                svc_order_no: svcOrderNo,
                error: "Order not found.",
            };
        } else {
            // Map status code to human-readable label
            const statusLabel = STATUS_CODE_LABELS[data.status] ?? data.status;
            result = {
                found: true,
                svc_order_no: data.svc_order_no,
                service_type: (data.service_type ?? undefined) as
                    | "d2d"
                    | "carry_in"
                    | "other"
                    | undefined,
                status: data.status,
                status_label: statusLabel,
                model_name: data.model_name ?? undefined,
                repair_cost_mxn: data.repair_cost_mxn ?? undefined,
                warranty_type: data.warranty_type ?? undefined,
                req_date: data.req_date ?? undefined,
                complete_date: data.complete_date ?? undefined,
                estimated_completion: data.estimated_completion ?? undefined,
                defect_desc: data.defect_desc ?? undefined,
                repair_action_desc: data.repair_action_desc ?? undefined,
                iris_condition_desc: data.iris_condition_desc ?? undefined,
                iris_symptom_desc: data.iris_symptom_desc ?? undefined,
                iris_defect_desc: data.iris_defect_desc ?? undefined,
                iris_repair_desc: data.iris_repair_desc ?? undefined,
                symptom_desc: data.symptom_desc ?? undefined,
            };

            // IQC enrichment — read the structured symptom_codes JSONB column
            // (populated by the GSPN sync) and attach Mexican-Spanish
            // descriptions. Codes outside TechRepair's IQC sheet keep desc_es=null
            // and fall back to GSPN's raw English desc. Wrapped in try/catch
            // because enrichment failures must NEVER block order lookup.
            if (Array.isArray(data.symptom_codes) && data.symptom_codes.length > 0) {
                try {
                    result.symptom_codes_enriched = data.symptom_codes.map(
                        (c: { code: string; desc: string | null }) => {
                            const entry = getIQCDescription(c.code);
                            return entry
                                ? {
                                      code: entry.code,
                                      desc_en: entry.desc_en,
                                      desc_es: entry.desc_es,
                                  }
                                : { code: c.code, desc_en: c.desc, desc_es: null };
                        },
                    );
                } catch (enrichErr) {
                    console.warn(
                        "[order-lookup] IQC enrichment failed:",
                        enrichErr,
                    );
                }
            }

            // Status-disclosure gate — see file header. Strip every field
            // that talks about repair progress when the policy disallows
            // proactive_status_disclosure for this (service_type, state).
            // The LLM gets a sparser object and literally cannot leak
            // status info because the fields aren't there.
            if (data.service_type) {
                try {
                    const policy = await getPolicyForServiceType(
                        data.service_type as "d2d" | "carry_in" | "other",
                        data.status,
                        client,
                    );
                    if (!policy.proactive_status_disclosure) {
                        const strippedFields: string[] = [];
                        const stripField = (field: keyof OrderLookupResult) => {
                            if (result[field] !== undefined) {
                                delete result[field];
                                strippedFields.push(field);
                            }
                        };
                        stripField("status");
                        stripField("status_label");
                        stripField("estimated_completion");
                        stripField("complete_date");
                        stripField("defect_desc");
                        stripField("repair_action_desc");
                        stripField("iris_condition_desc");
                        stripField("iris_symptom_desc");
                        stripField("iris_defect_desc");
                        stripField("iris_repair_desc");
                        stripField("symptom_desc");
                        stripField("symptom_codes_enriched");

                        // Audit trail — record the policy-driven strip so
                        // ops can later answer "did the agent see status
                        // for this customer?".
                        if (strippedFields.length > 0) {
                            logAgentThought(client, {
                                serviceType: data.service_type as
                                    | "d2d"
                                    | "carry_in"
                                    | "other",
                                thoughtType: "policy_skip",
                                metadata: {
                                    svc_order_no: data.svc_order_no,
                                    state: data.status,
                                    stripped_fields: strippedFields,
                                    policy_violated: "proactive_status_disclosure=false",
                                    reason: `${data.service_type} order in state ${data.status} — policy disallows status disclosure`,
                                },
                            }).catch((err) => {
                                console.error(
                                    "[order-lookup] logAgentThought failed (policy_skip):",
                                    err,
                                );
                            });
                        }
                    }
                } catch (policyErr) {
                    // Policy lookup failure must NOT block the lookup.
                    // Default-permissive (preserve existing behavior) — but
                    // record an audit row so a transient Supabase outage
                    // during e.g. (carry_in, ready_for_pickup) doesn't
                    // silently disable the gate.
                    console.error(
                        "[order-lookup] policy lookup failed, defaulting to permissive:",
                        policyErr,
                    );
                    logAgentThought(client, {
                        serviceType: data.service_type as
                            | "d2d"
                            | "carry_in"
                            | "other",
                        thoughtType: "policy_skip",
                        metadata: {
                            svc_order_no: data.svc_order_no,
                            state: data.status,
                            reason: "lookup_failed_default_permissive",
                            error: policyErr instanceof Error
                                ? policyErr.message
                                : String(policyErr),
                        },
                    }).catch((err) => {
                        console.error(
                            "[order-lookup] logAgentThought failed (lookup_failed_default_permissive):",
                            err,
                        );
                    });
                }
            }

            // Warranty-contradiction gate — when TechRepair GSPN has
            // already classified the order as Out of Warranty,
            // asking the customer for a purchase invoice is
            // contradictory (invoices serve to validate warranty,
            // and the warranty has already been ruled out). Strip
            // warranty_type at the tool boundary so the LLM cannot
            // reason about warranty status on this order.
            if (isOutOfWarranty(data.warranty_type)) {
                const originalWarrantyType = data.warranty_type;
                delete result.warranty_type;
                logAgentThought(client, {
                    serviceType: (data.service_type ?? null) as
                        | "d2d"
                        | "carry_in"
                        | "other"
                        | null,
                    thoughtType: "policy_skip",
                    metadata: {
                        svc_order_no: data.svc_order_no,
                        warranty_type: originalWarrantyType,
                        stripped_fields: ["warranty_type"],
                        policy_violated: "warranty_excluded",
                        reason: "order classified Out of Warranty by TechRepair GSPN — warranty_type stripped to prevent LLM asking for purchase invoice",
                    },
                }).catch((err) => {
                    console.error(
                        "[order-lookup] logAgentThought failed (warranty_excluded):",
                        err,
                    );
                });
            }
        }
    } catch (err) {
        result = {
            found: false,
            svc_order_no: svcOrderNo,
            error: err instanceof Error ? err.message : String(err),
        };
    }

    // Fire-and-forget tool invocation log
    const supabase = getSupabaseClient();
    if (supabase) {
        logToolInvocation(supabase, {
            toolName: "order_lookup",
            toolCategory: "whatsapp",
            success: result.found,
            inputParameters: { svc_order_no: svcOrderNo },
            outputResult: result as unknown as Record<string, unknown>,
            executionTimeMs: Date.now() - t0,
            errorMessage: result.error,
        }).catch(() => {/* non-fatal */ });
    }

    return result;
}
