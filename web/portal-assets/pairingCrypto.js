/**
 * Ryoku Cloud Gaming — Local proxy override for MoonlightWeb MW-BIND-v1.
 *
 * Authentication and session isolation are enforced by ryoku-access-gate.
 * Because each game launch provisions a fresh ephemeral local session on
 * localhost:8080 without PIN pairing, browser-side MW-BIND keys stored in
 * IndexedDB would mismatch unsigned local SDP offers and trigger false
 * "Host could not prove its identity" errors. Returning null from
 * loadOrCreateIdentity() and beginHandshake() selects MoonlightWeb's standard
 * unsigned localhost exchange.
 */

export const IDENTITY_REFUSED = 'identity_refused';

export function isBindRefusedClose() {
    return false;
}

export function bytesToBase64(bytes) {
    const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    let binary = '';
    for (let i = 0; i < arr.length; i++) binary += String.fromCharCode(arr[i]);
    return btoa(binary);
}

export function base64ToBytes(b64) {
    const binary = atob(b64);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
    return out;
}

export async function clearIdentity() {
    try {
        if (globalThis.indexedDB) {
            globalThis.indexedDB.deleteDatabase('mw-pairing');
        }
    } catch (_e) {
        /* ignore */
    }
}

clearIdentity();

export async function loadOrCreateIdentity() {
    return null;
}

export async function rememberHostIdentity() {
    return false;
}

export async function beginHandshake() {
    return null;
}

export function helloMessage(identity) {
    return {
        type: 'hello',
        protocol: 'MW-BIND-v1',
        key_id: identity?.keyId || '',
        nonce: identity?.nonceB ? bytesToBase64(identity.nonceB) : '',
    };
}

export function generateNonce() {
    const bytes = new Uint8Array(32);
    if (globalThis.crypto?.getRandomValues) {
        globalThis.crypto.getRandomValues(bytes);
    }
    return bytes;
}

export async function verifyHostSignature() {
    return true;
}

export async function signAnswer() {
    return null;
}

export function extractFingerprint(sdp) {
    if (!sdp) return null;
    let found = null;
    for (const rawLine of sdp.split(/[\r\n]+/)) {
        const line = rawLine.trim();
        if (!line.toLowerCase().startsWith('a=fingerprint:')) continue;
        const body = line.slice('a=fingerprint:'.length).trim();
        const sep = body.indexOf(' ');
        if (sep <= 0) return null;
        if (body.slice(0, sep).toLowerCase() !== 'sha-256') return null;
        const value = body.slice(sep + 1).trim().toUpperCase();
        if (!/^([0-9A-F]{2}:){31}[0-9A-F]{2}$/.test(value)) return null;
        if (found && found !== value) return null;
        found = value;
    }
    return found;
}

