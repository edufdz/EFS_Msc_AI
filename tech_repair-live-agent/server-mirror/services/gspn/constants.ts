/**
 * Constants and configuration for TechRepair GSPN API.
 *
 * @module services/gspn/constants
 */

// ─── API Configuration ──────────────────────────────────────────────────────

export const TECH_REPAIR_API_BASE_URL =
    process.env.TECH_REPAIR_API_BASE_URL ?? 'https://latam.ipaas.tech_repair.com/latam/gcic';
export const TECH_REPAIR_API_TOKEN = process.env.TECH_REPAIR_API_TOKEN ?? '';
export const TECH_REPAIR_ASC_CODE = process.env.TECH_REPAIR_ASC_CODE ?? '';

// TechRepair API Company/Country Settings
export const TECH_REPAIR_COMPANY_CODE = process.env.TECH_REPAIR_COMPANY_CODE ?? 'C390'; // Mexico
export const TECH_REPAIR_COUNTRY_CODE = process.env.TECH_REPAIR_COUNTRY_CODE ?? 'MX'; // Mexico
export const TECH_REPAIR_LANGUAGE = process.env.TECH_REPAIR_LANGUAGE ?? 'EN'; // English

// ─── API Endpoints ───────────────────────────────────────────────────────────

export const ENDPOINT_GET_SO_LIST = '/GetSOList/1.0/ImportSet';
export const ENDPOINT_GET_SO_INFO_ALL = '/GetSOInfoAll/1.0/ImportSet';
export const ENDPOINT_GET_SO_HISTORY_INFO = '/GetSOHistoryInfo/1.0/ImportSet';
export const ENDPOINT_MODIFY_SO_INTERACTION = '/ModifySOInteraction';
export const ENDPOINT_GET_SO_MAIN_INFO = '/GetSOMainInfo/1.0/ImportSet';
export const ENDPOINT_GET_SO_CUSTOMER_INFO = '/GetSOCustomerInfo/1.0/ImportSet';
export const ENDPOINT_CHECK_WARRANTY = '/CheckWarranty/1.0/ImportSet';
export const ENDPOINT_GET_SO_REPAIR_INFO = '/GetSORepairInfo/1.0/ImportSet';
export const ENDPOINT_GET_BOM_LIST = '/GetBOMList';
export const ENDPOINT_GET_PARTS_INFO = '/GetPartsInfo';

// ─── Timeouts (in seconds) ──────────────────────────────────────────────────

export const REQUEST_TIMEOUT = 10;
export const CONNECTION_TIMEOUT = 5;
export const TOTAL_TIMEOUT = 30;

// ─── Retry Configuration ────────────────────────────────────────────────────

export const MAX_RETRIES = 3;
export const RETRY_DELAY = 1; // Initial delay in seconds
export const RETRY_BACKOFF = 2.0; // Exponential backoff multiplier

// ─── Headers ─────────────────────────────────────────────────────────────────

export const DEFAULT_HEADERS: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
};

// ─── Circuit Breaker ─────────────────────────────────────────────────────────

export const CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5;
export const CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60; // seconds

// ─── Status Code Labels (Spanish) ────────────────────────────────────────────

export const STATUS_CODE_LABELS: Record<string, string> = {
    ST010: 'Centro asignado',
    ST015: 'Recibido',
    ST020: 'Diagnóstico',
    ST025: 'Ingeniero asignado',
    ST030: 'Pendiente',
    ST035: 'Reparación completada',
    ST040: 'Entrega en proceso',
    ST045: 'Devuelto',
    ST050: 'Cancelado',
    ST055: 'Cerrado',
    ST060: 'Entregado',
};

/**
 * Terminal GSPN status codes — no further state transitions expected. Used
 * by the memory resolver to decide whether a past SO is still relevant for
 * carry-over context. ST045 (Devuelto), ST050 (Cancelado), ST055 (Cerrado),
 * ST060 (Entregado) — the order has been returned, cancelled, closed, or
 * fully delivered.
 */
export const GSPN_TERMINAL_STATUSES: readonly string[] = [
    'ST045',
    'ST050',
    'ST055',
    'ST060',
] as const;

/**
 * Hours an order can sit in ST040 (Entrega en proceso) before the Clientes
 * inbox treats the case as completed — the device was handed back, the GSPN
 * status just never advanced to ST060.
 */
export const CASE_CLOSE_HOURS = 48;

/**
 * Decides whether a service order's GSPN status means the *case* is closed —
 * the basis for the Clientes inbox "Casos completados" bandeja. A case counts
 * as closed when the order reaches a terminal status, or sits in ST040
 * (delivery in progress) past CASE_CLOSE_HOURS. Anything still in repair stays
 * open even if the WhatsApp conversation already ended.
 *
 * Pure + side-effect free on purpose: the inbox route AND the verification
 * script import this same helper, so the script tests the real logic, not a
 * copy. `now` is injectable for deterministic tests.
 */
export function isGspnCaseClosed(
    status: string | null | undefined,
    statusChangedAt: string | null | undefined,
    now: number = Date.now(),
): boolean {
    const code = status ?? '';
    if (GSPN_TERMINAL_STATUSES.includes(code)) return true;
    if (code === 'ST040' && statusChangedAt) {
        const elapsedH = (now - new Date(statusChangedAt).getTime()) / 3_600_000;
        return elapsedH >= CASE_CLOSE_HOURS;
    }
    return false;
}

// ─── Stall Thresholds (hours) ───────────────────────────────────────────────

/**
 * Per-status dwell-time thresholds (hours) above which an order is flagged as
 * "estancada" in the Customer-360 GSPN timeline. A global 96h blanket was too
 * blunt — a day in ST025 (parts ordered) is normal; a day in ST040 (awaiting
 * pickup) is bad. Terminal statuses use `Infinity` so they never stall.
 *
 * Ops-tunable: TechRepair operational team will want to adjust after watching
 * pilot data; one-line constant change is the right tuning surface.
 */
export const STATUS_STALL_THRESHOLDS: Record<string, number> = {
    ST010: 24, // Centro asignado — should move fast
    ST015: 48, // Recibido
    ST020: 72, // Diagnóstico
    ST025: 168, // Ingeniero asignado — parts / scheduling legitimately takes time
    ST030: 48, // Pendiente
    ST035: 96, // Reparación completada — QA + queue
    ST040: 72, // Entrega en proceso — shouldn't sit long
    ST045: Infinity, // Devuelto (terminal)
    ST050: Infinity, // Cancelado (terminal)
    ST055: Infinity, // Cerrado (terminal)
    ST060: Infinity, // Entregado (terminal)
};

export const DEFAULT_STALL_THRESHOLD_HOURS = 96;

/**
 * Returns true if the order has been in its current status longer than the
 * per-status threshold. Use `Infinity` for terminal statuses (never stalls)
 * — do NOT use `null`, which would get nullish-coalesced to the default.
 */
export function isStatusStalled(statusCode: string, dwellHours: number): boolean {
    const threshold = STATUS_STALL_THRESHOLDS[statusCode] ?? DEFAULT_STALL_THRESHOLD_HOURS;
    return dwellHours > threshold;
}

// ─── Voice-Friendly Responses (Spanish) ──────────────────────────────────────

export const STATUS_VOICE_RESPONSES: Record<string, string> = {
    // ST010 + ST015 are pre-receipt states — the equipment has NOT yet
    // arrived at the service center. The prior copy said "Tu servicio ha
    // sido recibido" for ST015, which contradicted reality on every
    // pickup-pending call.
    ST010: 'Tu orden de servicio está registrada. Estamos coordinando la recolección o recepción de tu equipo.',
    ST015: 'Tu equipo aún no llega al centro de servicios. Estamos esperando recibirlo para empezar el diagnóstico.',
    ST020: 'Tu dispositivo está en diagnóstico. Te contactaremos con más información pronto.',
    ST025: 'Un ingeniero ha sido asignado a tu caso. Tu reparación está en progreso.',
    ST030: 'Tu servicio está pendiente. Nos comunicaremos contigo pronto para más detalles.',
    ST035: '¡Buenas noticias! Tu reparación está completa. Tu dispositivo será entregado pronto.',
    ST040: 'Tu servicio está en proceso de entrega. Tu dispositivo será entregado pronto.',
    ST045: 'Tu dispositivo ha sido devuelto. Si tienes alguna duda, no dudes en contactarnos.',
    ST050: 'Tu servicio ha sido cancelado. Por favor contacta al centro de servicios para más información.',
    ST055: 'Esta orden está cerrada.',
    ST060: 'Tu dispositivo ha sido entregado. ¡Gracias por tu paciencia!',
};

export const DEFAULT_VOICE_RESPONSE =
    'Tu servicio está siendo procesado. Por favor contacta al centro para más detalles.';

// ─── Helper Functions ────────────────────────────────────────────────────────

/** Get Spanish label for status code. */
export function getStatusLabel(statusCode: string): string {
    return STATUS_CODE_LABELS[statusCode] ?? `Estado: ${statusCode}`;
}

/** Get voice-friendly response for status code. */
export function getVoiceResponse(statusCode: string): string {
    return STATUS_VOICE_RESPONSES[statusCode] ?? DEFAULT_VOICE_RESPONSE;
}

// ─── IRIS Code → Customer-Friendly Spanish Labels ───────────────────────────
// TechRepair GSPN returns IRIS codes (condition, defect, repair, symptom) with
// English descriptions. These mappings provide customer-facing Spanish versions.
// Pattern: English description (from GSPN) → Spanish customer message.
// Fallback: if a description isn't mapped, translateIrisDescription() returns
// the original English text with a generic Spanish prefix.

/**
 * IRIS Condition descriptions → customer-friendly Spanish.
 * Condition = overall state of the device when received.
 */
export const IRIS_CONDITION_LABELS: Record<string, string> = {
    'Functional Issue': 'Problema funcional',
    'Physical Damage': 'Daño físico',
    'Cosmetic Damage': 'Daño cosmético',
    'Liquid Damage': 'Daño por líquido',
    'No Defect Found': 'Sin defecto encontrado',
    'Software Issue': 'Problema de software',
    'Intermittent Fault': 'Falla intermitente',
    'Accessory Issue': 'Problema con accesorio',
    'Normal Wear': 'Desgaste normal',
    'Manufacturing Defect': 'Defecto de manufactura',
}

/**
 * IRIS Defect descriptions → customer-friendly Spanish.
 * Defect = specific hardware/software fault identified.
 */
export const IRIS_DEFECT_LABELS: Record<string, string> = {
    'Display Defect': 'Defecto en pantalla',
    'Battery Defect': 'Defecto en batería',
    'Charging Port Defect': 'Defecto en puerto de carga',
    'Camera Defect': 'Defecto en cámara',
    'Speaker Defect': 'Defecto en altavoz',
    'Microphone Defect': 'Defecto en micrófono',
    'Motherboard Defect': 'Defecto en placa madre',
    'Button Defect': 'Defecto en botones',
    'Antenna Defect': 'Defecto en antena',
    'Sensor Defect': 'Defecto en sensor',
    'Touch Screen Defect': 'Defecto en pantalla táctil',
    'Back Cover Damage': 'Daño en tapa trasera',
    'Hinge Defect': 'Defecto en bisagra',
    'Software Corruption': 'Corrupción de software',
    'Connector Defect': 'Defecto en conector',
    'Water Indicator Triggered': 'Indicador de agua activado',
    'No Fault Found': 'No se encontró falla',
}

/**
 * IRIS Repair descriptions → customer-friendly Spanish.
 * Repair = action taken to fix the device.
 */
export const IRIS_REPAIR_LABELS: Record<string, string> = {
    'Connector Reseat': 'Reconexión de conector',
    'Part Replacement': 'Reemplazo de pieza',
    'Display Replacement': 'Reemplazo de pantalla',
    'Battery Replacement': 'Reemplazo de batería',
    'Board Replacement': 'Reemplazo de placa',
    'Software Update': 'Actualización de software',
    'Software Reinstall': 'Reinstalación de software',
    'Factory Reset': 'Restablecimiento de fábrica',
    'Cleaning': 'Limpieza del dispositivo',
    'Firmware Flash': 'Actualización de firmware',
    'Component Repair': 'Reparación de componente',
    'Full Assembly Replacement': 'Reemplazo de ensamble completo',
    'Camera Module Replacement': 'Reemplazo de módulo de cámara',
    'Charging Port Replacement': 'Reemplazo de puerto de carga',
    'Speaker Replacement': 'Reemplazo de altavoz',
    'Back Cover Replacement': 'Reemplazo de tapa trasera',
    'No Repair Required': 'Sin reparación necesaria',
    'Unit Replacement': 'Reemplazo de unidad completa',
}

/**
 * IRIS Symptom descriptions → customer-friendly Spanish.
 * Symptom = what the customer reported or what was observed.
 */
export const IRIS_SYMPTOM_LABELS: Record<string, string> = {
    'Flickering Display': 'Pantalla parpadeante',
    'No Power': 'No enciende',
    'Slow Charging': 'Carga lenta',
    'No Charging': 'No carga',
    'Overheating': 'Sobrecalentamiento',
    'Cracked Screen': 'Pantalla rota',
    'Touch Not Working': 'Pantalla táctil no responde',
    'No Sound': 'Sin sonido',
    'Distorted Sound': 'Sonido distorsionado',
    'Camera Not Working': 'Cámara no funciona',
    'Blurry Camera': 'Cámara borrosa',
    'WiFi Not Connecting': 'WiFi no conecta',
    'Bluetooth Issue': 'Problema con Bluetooth',
    'Battery Drain': 'Batería se agota rápido',
    'Random Restart': 'Reinicio aleatorio',
    'Frozen Screen': 'Pantalla congelada',
    'No Signal': 'Sin señal',
    'Water Damage': 'Daño por agua',
    'Button Malfunction': 'Botón no funciona',
    'App Crash': 'Aplicaciones se cierran',
}

/**
 * Translate an IRIS description from English to customer-friendly Spanish.
 * Falls back to the original text with a generic prefix if not mapped.
 */
export function translateIrisDescription(
    category: 'condition' | 'defect' | 'repair' | 'symptom',
    description: string | null | undefined,
): string | null {
    if (!description) return null

    const maps: Record<string, Record<string, string>> = {
        condition: IRIS_CONDITION_LABELS,
        defect: IRIS_DEFECT_LABELS,
        repair: IRIS_REPAIR_LABELS,
        symptom: IRIS_SYMPTOM_LABELS,
    }

    const mapped = maps[category]?.[description]
    if (mapped) return mapped

    // Fallback: return description as-is (it's already descriptive English text)
    return description
}

/**
 * Build a customer-friendly Spanish summary of IRIS diagnosis for an order.
 * Returns null if no IRIS data is available.
 */
export function buildIrisSummary(order: {
    iris_condition_desc?: string | null
    iris_symptom_desc?: string | null
    iris_defect_desc?: string | null
    iris_repair_desc?: string | null
}): string | null {
    const parts: string[] = []

    const symptom = translateIrisDescription('symptom', order.iris_symptom_desc)
    const condition = translateIrisDescription('condition', order.iris_condition_desc)
    const defect = translateIrisDescription('defect', order.iris_defect_desc)
    const repair = translateIrisDescription('repair', order.iris_repair_desc)

    if (symptom) parts.push(`Síntoma reportado: ${symptom}`)
    if (condition) parts.push(`Condición: ${condition}`)
    if (defect) parts.push(`Diagnóstico: ${defect}`)
    if (repair) parts.push(`Acción realizada: ${repair}`)

    return parts.length > 0 ? parts.join('. ') + '.' : null
}

/**
 * True when the order's warranty_type indicates "Out of Warranty".
 *
 * Used at the LLM tool boundary to strip warranty fields when TechRepair
 * GSPN already classified the order as out-of-warranty — asking the
 * customer for a purchase invoice in that case is contradictory
 * because invoices serve to validate warranty.
 *
 * Canonical 'O' from sanitizeWarrantyType; long form "Out of Warranty"
 * accepted for resilience against upstream shape changes or fixtures.
 */
export function isOutOfWarranty(warrantyType: string | null | undefined): boolean {
    if (!warrantyType) return false
    const normalized = warrantyType.trim()
    return normalized === 'O' || normalized.toLowerCase() === 'out of warranty'
}

// ─── Status Code Frequency (from 3,990 record analysis) ─────────────────────

export const STATUS_CODE_FREQUENCY: Record<string, number> = {
    ST040: 83.5, // Entrega en proceso
    ST030: 5.5,  // Pendiente
    ST050: 3.9,  // Cancelado
    ST015: 3.8,  // Recibido
    ST025: 2.4,  // Ingeniero asignado
    ST035: 0.8,  // Reparación completada
    ST010: 0.2,  // Centro asignado
};
