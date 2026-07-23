/**
 * @deprecated This prompt file is no longer used
 * WhatsApp now uses extractInteractionInsights() from services/analysis/unified-extraction.ts
 *
 * The unified extraction service consolidates voice and WhatsApp extraction into a single,
 * feature-parity implementation using UnifiedInteractionSchema (Epic 2, Task 2.1 & 2.2).
 *
 * This file is kept for reference only and safe to delete after main branch migration.
 * The unified service handles both channels with identical extraction logic and CRM fields.
 *
 * TODO: Remove this file after main branch migration is complete
 */

export const MEMORY_EXTRACTION_SYSTEM_PROMPT =
    "Extrae 3-5 hechos clave PERSISTENTES sobre el cliente de esta conversación de WhatsApp. " +
    "Incluye: nombre, dispositivo, garantía, problemas recurrentes, preferencias de idioma. " +
    "IGNORAR: emociones del momento, detalles logísticos de esta conversación, saludos. " +
    "Responde SOLO con un array JSON de strings, sin markdown ni texto adicional.";
