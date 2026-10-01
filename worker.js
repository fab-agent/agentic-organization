// agent.fab.engineering: static assets + the contact form endpoint (/api/contact -> D1).
const INTENTS = new Set(['demo', 'contact', 'sponsor']);
const LANGS = new Set(['tr', 'en', 'de', 'es']);
const MAX_PER_HOUR = 5;

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });

async function sha256(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

function clean(v, max) {
  return String(v ?? '').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '').trim().slice(0, max);
}

async function handleContact(request, env) {
  if (request.method !== 'POST') return json({ ok: false, error: 'method_not_allowed' }, 405);

  const origin = request.headers.get('Origin');
  if (origin && new URL(origin).host !== new URL(request.url).host) return json({ ok: false, error: 'forbidden' }, 403);

  let b;
  try { b = await request.json(); } catch { return json({ ok: false, error: 'bad_json' }, 400); }

  // Bots: a filled honeypot or an instant submit gets a fake success and is not stored.
  if (clean(b.website, 200) || Number(b.elapsed) < 2500) return json({ ok: true, ref: 'FAB-0000' });

  const intent = clean(b.intent, 20);
  const name = clean(b.name, 120);
  const email = clean(b.email, 200).toLowerCase();
  const message = clean(b.message, 4000);
  if (!INTENTS.has(intent) || name.length < 2 || message.length < 5 || !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) {
    return json({ ok: false, error: 'invalid' }, 422);
  }
  const org = clean(b.org, 160);
  const topic = clean(b.topic, 120);
  const lang = LANGS.has(b.lang) ? b.lang : 'tr';

  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const ipHash = (await sha256(`${ip}|fab-agent-landing`)).slice(0, 32);

  const recent = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM leads WHERE ip_hash = ?1 AND created_at > strftime('%Y-%m-%dT%H:%M:%fZ','now','-1 hour')"
  ).bind(ipHash).first();
  if ((recent?.n ?? 0) >= MAX_PER_HOUR) return json({ ok: false, error: 'rate_limited' }, 429);

  const ref = 'FAB-' + crypto.randomUUID().replace(/-/g, '').slice(0, 6).toUpperCase();
  await env.DB.prepare(
    'INSERT INTO leads (ref, intent, name, email, org, topic, message, lang, country, ip_hash, ua) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)'
  ).bind(ref, intent, name, email, org, topic, message, lang, request.cf?.country ?? null, ipHash,
         clean(request.headers.get('User-Agent'), 200)).run();

  return json({ ok: true, ref });
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname === '/api/contact') {
      try { return await handleContact(request, env); }
      catch (e) { console.error('contact error', e); return json({ ok: false, error: 'server' }, 500); }
    }
    return env.ASSETS.fetch(request);
  },
};
