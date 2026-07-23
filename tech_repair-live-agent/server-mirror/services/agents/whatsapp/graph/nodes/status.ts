/**
 * Status Node
 * ===========
 * Handles order-status inquiries only. PRICING intent is handled by
 * `pricing-answer.ts` — this node must never read the repair_pricing // ci-guard:allow repair_pricing
 * estimates table (enforced by scripts/ci/verify-agent-wiring.sh).
 * Uses tools to look up order info, then LLM to format response.
 */

import { ChatPromptTemplate } from "@langchain/core/prompts";
import { getWhatsAppDynamicConfig } from "@/services/agents/whatsapp/config";
import type { ToolCall } from "@/services/agents/whatsapp/models";
import { STATUS_USER_PROMPT, getStatusSystemPrompt } from "@/services/agents/whatsapp/prompts/status";
import { buildWhatsAppCarryInAddendum } from "@/services/agents/whatsapp/prompts/carry-in";
import { loadAgentConfig } from "@/services/agents/shared/dynamic-config";
import {
    createLLM,
    createFallbackModel,
    withProviderFallback,
} from "@/services/agents/whatsapp/llm-factory";
import { extractUsage } from "@/services/agents/whatsapp/llm-usage";
import {
    type WhatsAppStateType,
    getCustomerInfo,
    getActiveOrders,
    formatConversationHistory,
} from "@/services/agents/whatsapp/graph/state";
import { lookupOrder } from "@/services/agents/whatsapp/tools/order-lookup";
import { rememberServiceOrder } from "@/services/meta/order-memory";
import { logAgentThought } from "@/shared/supabase-logger";
import { getSupabaseClient } from "@/shared/supabase";

// =============================================================================
// Tool Execution
// =============================================================================

interface ToolResult {
    toolCalls: ToolCall[];
    orderData: string;
}

/**
 * Execute tools based on available context.
 *
 * - If active orders exist: look up detailed status for each
 * - Otherwise: try to extract order number from message
 */
async function executeTools(
    state: WhatsAppStateType,
): Promise<ToolResult> {
    const toolCalls: ToolCall[] = [];
    const results: string[] = [];
    const orders = getActiveOrders(state);
    const currentMessage = state.context?.current_message?.content ?? "";

    // Context for remembering a confirmed folio (fire-and-forget, see below).
    const supabase = getSupabaseClient();
    const phone = state.context?.customer?.phone_number;
    const conversationId = state.context?.metadata?.conversation_id as string | undefined;

    if (orders.length > 0) {
        // Look up status for each known order
        for (const order of orders) {
            try {
                const result = await lookupOrder(order.svc_order_no);
                if (supabase && result.found) {
                    void rememberServiceOrder(supabase, {
                        phone,
                        conversationId,
                        svcOrderNo: order.svc_order_no,
                    }).catch(() => {/* non-fatal */});
                }
                toolCalls.push({
                    tool_name: "order_lookup",
                    tool_input: { svc_order_no: order.svc_order_no },
                    tool_output: result,
                });
                results.push(JSON.stringify(result, null, 2));
            } catch (err) {
                const errMsg = err instanceof Error ? err.message : String(err);
                toolCalls.push({
                    tool_name: "order_lookup",
                    tool_input: { svc_order_no: order.svc_order_no },
                    tool_output: { error: errMsg },
                });
                results.push(`Error looking up ${order.svc_order_no}: ${errMsg}`);
            }
        }
    } else {
        // Try to extract order number from message
        const orderMatch = currentMessage.match(
            /\b(?:svc[-_]?)?(\d{10,})\b/i,
        );
        if (orderMatch) {
            const svcOrderNo = orderMatch[1];
            try {
                const result = await lookupOrder(svcOrderNo);
                if (supabase && result.found) {
                    // The carry-in case: customer typed a folio the phone lookup
                    // couldn't find. Remember it so the next chat already knows it.
                    void rememberServiceOrder(supabase, {
                        phone,
                        conversationId,
                        svcOrderNo,
                    }).catch(() => {/* non-fatal */});
                }
                toolCalls.push({
                    tool_name: "order_lookup",
                    tool_input: { svc_order_no: svcOrderNo },
                    tool_output: result,
                });
                results.push(JSON.stringify(result, null, 2));
            } catch (err) {
                const errMsg = err instanceof Error ? err.message : String(err);
                results.push(`Error: ${errMsg}`);
            }
        }
    }

    return {
        toolCalls,
        orderData: results.join("\n\n") || "No order data available.",
    };
}

// =============================================================================
// Status Node
// =============================================================================

export async function statusNode(
    state: WhatsAppStateType,
): Promise<Partial<WhatsAppStateType>> {
    const config = await getWhatsAppDynamicConfig();
    const dbConfig = await loadAgentConfig("whatsapp");

    try {
        // 1. Execute tools
        const { toolCalls, orderData } = await executeTools(state);

        // 2. Format response with LLM (Anthropic primary, gpt-5.2 fallback
        //    so customer never sees the Spanish fallback when only one
        //    provider is having a bad day).
        const llm = withProviderFallback(
            createLLM(state.laneConfig),
            createFallbackModel(state.laneConfig),
        );

        const customer = getCustomerInfo(state);
        const customerInfo = customer
            ? `Nombre: ${customer.name ?? "No disponible"}, Tel: ${customer.phone_number}`
            : "No customer info available.";

        const statusPromptOverride = dbConfig?.prompts?.status;
        // Append the carry-in guardrail when any active order is carry_in so
        // the LLM never offers home delivery for in-store orders. Null (no
        // carry-in) → base prompt unchanged for D2D/other.
        const carryInAddendum = buildWhatsAppCarryInAddendum(getActiveOrders(state));
        const statusSystemPrompt = carryInAddendum
            ? `${getStatusSystemPrompt(statusPromptOverride)}\n\n${carryInAddendum}`
            : getStatusSystemPrompt(statusPromptOverride);
        const prompt = ChatPromptTemplate.fromMessages([
            ["system", statusSystemPrompt],
            ["human", STATUS_USER_PROMPT],
        ]);

        const chain = prompt.pipe(llm);
        const response = await chain.invoke({
            memory_directives: state.context?.memory_directives ?? "",
            customer_info: customerInfo,
            order_data: orderData,
            tool_results: toolCalls.map((t) => `${t.tool_name}: ${JSON.stringify(t.tool_output)}`).join("\n"),
            conversation_history: formatConversationHistory(state),
            current_message: state.context?.current_message?.content ?? "",
            max_length: config.maxResponseLength,
            support_phone: config.supportPhone,
        });

        const text =
            typeof response.content === "string" ? response.content : "";

        return {
            responseText: text,
            toolCalls,
            llmUsage: extractUsage(response),
        };
    } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        const cause = state.laneConfig == null
            ? "lane_config"
            : /anthropic|openai/i.test(error.message)
                ? "llm_api"
                : /supabase|postgres/i.test(error.message)
                    ? "db"
                    : "unknown";

        const supabase = getSupabaseClient();
        const conversationId = state.context?.metadata?.conversation_id as string | undefined;
        if (supabase && conversationId) {
            logAgentThought(supabase, {
                conversationId,
                phone: state.context?.customer?.phone_number,
                stepName: "status_error",
                thoughtContent:
                    `${error.name}: ${error.message} | ` +
                    `cause=${cause} | ` +
                    `lane_config=${state.laneConfig ? "set" : "null"} | ` +
                    `intent=${state.intent} | ` +
                    `active_orders=${getActiveOrders(state).length}`,
            }).catch(() => { /* non-fatal */ });
        }

        console.error("[status] Node error:", err);
        return {
            responseText:
                "Lo siento, hubo un problema al consultar el estado de su orden. Por favor intente nuevamente.",
            error: `Status error: ${error.message}`,
        };
    }
}
