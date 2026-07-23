/**
 * TechRepair Engineer Symptom Codes (IQC)
 * =====================================
 * Authoritative Mexican-Spanish descriptions for the IQC codes TechRepair Polanco
 * documented for the México service center. These codes appear on customer
 * work-order paperwork and on GSPN's `symptom_codes` array; agents reference
 * them when customers ask "qué significa T71".
 *
 * Source: CODIGOS DE IQC.xlsx (provided by TechRepair Polanco operations).
 * Nine entries had English text truncated by TechRepair's spreadsheet column
 * width — those are flagged with a `// note: expanded from "..."` comment
 * preserving the original raw text so a future reviewer can confirm the
 * expansion with TechRepair. Worst-case impact of a wrong guess: customer
 * hears a slightly off Spanish wording for that specific code; no safety
 * risk, fixable in a one-line edit.
 *
 * Both the WhatsApp and outbound voice agents read from this file via the
 * helpers below. Keep this as the SINGLE source of truth — never duplicate
 * the Spanish wording elsewhere.
 *
 * @module data/iqc-codes
 */

// ─── Types ──────────────────────────────────────────────────────────────────

export interface IQCCodeEntry {
    desc_en: string;
    desc_es: string;
}

export interface IQCDescription {
    code: string;
    desc_en: string;
    desc_es: string;
}

// ─── Code Table ─────────────────────────────────────────────────────────────

/**
 * The 39 IQC codes from TechRepair's reference sheet. Keys are the canonical
 * uppercase code; lookups via {@link getIQCDescription} normalize input
 * (trim + uppercase) before reading this map.
 */
export const IQC_CODES: Record<string, IQCCodeEntry> = {
    // ─── 3-digit legacy codes ───
    '111': {
        desc_en: 'NO POWER',
        desc_es: 'El equipo no enciende.',
    },
    '131': {
        desc_en: 'No or faulty display',
        desc_es: 'La pantalla no funciona o presenta falla.',
    },
    '166': {
        desc_en: 'Damaged plug/socket/terminal/connector',
        desc_es: 'Conector, terminal o puerto dañado.',
    },
    '723': {
        desc_en: 'Operating system locks out/crashes/hangs',
        desc_es: 'El sistema operativo se traba, se reinicia o se cierra.',
    },
    '746': {
        // note: expanded from "Pointing device  / touchscreen not track" (truncated in source)
        desc_en: 'Pointing device / touchscreen not tracking',
        desc_es: 'La pantalla táctil o el touchpad no rastrea correctamente.',
    },
    '749': {
        desc_en: 'Trackpad / touchscreen surface damaged',
        desc_es: 'Superficie del touchpad o pantalla táctil dañada.',
    },
    '781': {
        desc_en: 'USB interface problem',
        desc_es: 'Falla en la interfaz USB.',
    },
    '788': {
        desc_en: 'LAN / Wifi problem',
        desc_es: 'Falla de red LAN o WiFi.',
    },

    // ─── Special-format codes ───
    '28C': {
        desc_en: 'Set locked',
        desc_es: 'Equipo bloqueado.',
    },

    // ─── A-prefix ───
    A51: {
        desc_en: 'Water leakage',
        desc_es: 'Filtración o entrada de líquido.',
    },

    // ─── T-prefix (general symptoms) ───
    T02: {
        // note: expanded from "Google FRP/TechRepair reactivation unlock r" (truncated in source)
        desc_en: 'Google FRP / TechRepair reactivation unlock request',
        desc_es: 'Solicitud de desbloqueo de reactivación (Google FRP o cuenta TechRepair).',
    },
    T03: {
        desc_en: 'NCK, RGCK unlock request',
        desc_es: 'Solicitud de desbloqueo de red (NCK / RGCK).',
    },
    T12: {
        desc_en: 'No power on',
        desc_es: 'El equipo no enciende.',
    },
    T13: {
        // note: expanded from "Lockup while booting(stopping at logo sc" (truncated in source)
        desc_en: 'Lockup while booting (stopping at logo screen)',
        desc_es: 'Se traba al iniciar y se queda en la pantalla del logo.',
    },
    T21: {
        desc_en: 'No display (black screen)',
        desc_es: 'Sin imagen, pantalla en negro.',
    },
    T22: {
        desc_en: 'White screen',
        desc_es: 'Pantalla en blanco.',
    },
    T2C: {
        desc_en: 'Water sign',
        desc_es: 'Indicador de humedad activado.',
    },
    T71: {
        desc_en: "TSP (Touch) doesn't work",
        desc_es: 'La pantalla táctil no responde.',
    },
    T83: {
        desc_en: 'USB connectivity problem',
        desc_es: 'Falla de conexión USB.',
    },
    T98: {
        desc_en: 'Damaged IF connector (broken pins)',
        desc_es: 'Conector interno dañado, pines rotos.',
    },
    T9C: {
        desc_en: 'Water damage / corrosion',
        desc_es: 'Daño por agua o corrosión.',
    },
    T9E: {
        desc_en: 'Burnt',
        desc_es: 'Equipo quemado.',
    },

    // ─── F-prefix (functional failures) ───
    F01: {
        desc_en: 'NO POWER',
        desc_es: 'El equipo no enciende.',
    },
    F02: {
        // note: expanded from "NO POWER - Folder Fa" (truncated in source)
        desc_en: 'NO POWER — Folder fail',
        desc_es: 'No enciende, falla en el folder o bisagra.',
    },
    F11: {
        desc_en: 'LCD blank',
        desc_es: 'Pantalla LCD en blanco, sin imagen.',
    },
    F18: {
        desc_en: 'SMS / MMS fail',
        desc_es: 'Falla al enviar o recibir SMS o MMS.',
    },
    F88: {
        desc_en: 'Phone locked',
        desc_es: 'Equipo bloqueado.',
    },
    FBW: {
        desc_en: 'AUTO POWER',
        desc_es: 'Apagado o encendido automático no controlado.',
    },
    FCA: {
        // note: expanded from "NO POWER UP WITH TES" (truncated in source)
        desc_en: 'NO POWER UP WITH TEST',
        desc_es: 'No enciende durante la prueba.',
    },
    FCL: {
        desc_en: 'Phone powers off',
        desc_es: 'El equipo se apaga.',
    },
    FD6: {
        // note: expanded from "IF Corrosion or Liqu" (truncated in source)
        desc_en: 'IF corrosion or liquid',
        desc_es: 'Corrosión o líquido en el conector interno.',
    },
    FEX: {
        desc_en: 'Touchpad fail',
        desc_es: 'Falla en touchpad.',
    },
    FFM: {
        // note: expanded from "LOCK UP DURING OPERA" (truncated in source)
        desc_en: 'Lock up during operation',
        desc_es: 'El equipo se traba durante el uso.',
    },
    FG8: {
        desc_en: 'WI-FI failure',
        desc_es: 'Falla de WiFi.',
    },
    FHE: {
        // note: expanded from "Reactivation Lock Tr" (truncated in source)
        desc_en: 'Reactivation Lock triggered',
        desc_es: 'Bloqueo de reactivación activado.',
    },
    FHN: {
        desc_en: 'Reactivation unlock',
        desc_es: 'Desbloqueo de reactivación.',
    },
    FK7: {
        desc_en: 'USB to PC connection',
        desc_es: 'Falla de conexión USB con la computadora.',
    },
    FL1: {
        // note: expanded from "LCD White Spot Failu" (truncated in source)
        desc_en: 'LCD white spot failure',
        desc_es: 'Mancha blanca en la pantalla LCD.',
    },
    FPL: {
        desc_en: 'Black spot on LCD',
        desc_es: 'Mancha negra en la pantalla LCD.',
    },
};

// ─── Helpers ────────────────────────────────────────────────────────────────

/**
 * Look up a single IQC code. Case-insensitive, trims whitespace.
 * Returns `null` if the code isn't in our table — callers MUST handle this
 * (typically by falling through to GSPN's own description or escalating).
 */
export function getIQCDescription(code: string | null | undefined): IQCDescription | null {
    if (!code) return null;
    const normalized = code.trim().toUpperCase();
    if (!normalized) return null;
    const entry = IQC_CODES[normalized];
    if (!entry) return null;
    return { code: normalized, desc_en: entry.desc_en, desc_es: entry.desc_es };
}

