/**
 * Cloudflare Worker: live demo call
 *
 * POST /  { "phone": "+15145550199", "token": "<turnstile-token>" }
 *
 * 1. Validates the Turnstile token.
 * 2. Places an outbound call through Retell AI.
 *
 * Deploy:
 *   npx wrangler deploy workers/live-call.js --name laval-live-call
 */

const TURNSTILE_VERIFY_URL =
  'https://challenges.cloudflare.com/turnstile/v0/siteverify';
const TURNSTILE_SECRET = '0x4AAAAAAFxeQCDsz_rR5ya1NzLTVkZLIvY';

const RETELL_CALL_URL = 'https://api.retellai.com/v2/create-phone-call';
const RETELL_API_KEY = 'key_84e179b0af810a15d051c506823a';
const RETELL_FROM_NUMBER = '+14502353996';
const RETELL_AGENT_ID = 'agent_0c63ec5a76c5174a379b3a6caa';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...CORS_HEADERS,
    },
  });
}

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (request.method !== 'POST') {
      return json({ success: false, error: 'Method not allowed' }, 405);
    }

    // ---- Parse body ------------------------------------------------------
    let payload;
    try {
      payload = await request.json();
    } catch {
      return json({ success: false, error: 'Invalid JSON body' }, 400);
    }

    const phone = typeof payload?.phone === 'string' ? payload.phone.trim() : '';
    const token = typeof payload?.token === 'string' ? payload.token.trim() : '';

    if (!phone || !token) {
      return json(
        { success: false, error: 'Both "phone" and "token" are required' },
        400,
      );
    }

    // ---- Verify Turnstile ------------------------------------------------
    const verifyBody = new FormData();
    verifyBody.append('secret', TURNSTILE_SECRET);
    verifyBody.append('response', token);

    let verification;
    try {
      const verifyResponse = await fetch(TURNSTILE_VERIFY_URL, {
        method: 'POST',
        body: verifyBody,
      });
      verification = await verifyResponse.json();
    } catch {
      return json(
        { success: false, error: 'Could not verify the challenge' },
        403,
      );
    }

    if (!verification?.success) {
      return json({ success: false, error: 'Challenge verification failed' }, 403);
    }

    // ---- Place the call --------------------------------------------------
    let callResponse;
    try {
      callResponse = await fetch(RETELL_CALL_URL, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${RETELL_API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          from_number: RETELL_FROM_NUMBER,
          to_number: phone,
          override_agent_id: RETELL_AGENT_ID,
        }),
      });
    } catch {
      return json({ success: false, error: 'Call provider unreachable' }, 502);
    }

    if (!callResponse.ok) {
      return json({ success: false, error: 'Call could not be started' }, 502);
    }

    return json({ success: true }, 200);
  },
};
