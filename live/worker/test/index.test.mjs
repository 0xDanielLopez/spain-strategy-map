import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const fx = (n) => JSON.parse(readFileSync(new URL(`./fixtures/${n}.json`, import.meta.url), "utf8"));
const store = new Map();
globalThis.caches = {
  default: {
    async match(req) { const r = store.get(req.url); return r ? r.clone() : undefined; },
    async put(req, res) { store.set(req.url, res); },
  },
};
let fail = false;
const calls = [];
globalThis.fetch = async (url, init) => {
  calls.push({ url: String(url), ua: init.headers["User-Agent"], key: init.headers["x-api-key"] });
  if (fail) throw new Error("down");
  const u = String(url);
  const body = u.includes("vehicle_positions_LD") ? fx("vehicle_positions_LD")
    : u.includes("vehicle_positions") ? fx("vehicle_positions")
    : u.includes("trip_updates_LD") ? fx("trip_updates_LD")
    : u.includes("trip_updates") ? fx("trip_updates")
    : { ac: fx("adsb")[0].ac };
  return new Response(JSON.stringify(body));
};
const { default: worker } = await import("../src/index.js");
const env = { ALLOWED_ORIGINS: "https://ok.example,http://localhost:8799" };
const ctx = { waitUntil() {} };
const req = (path, origin, method = "GET") => new Request("https://x.test" + path, { method, headers: origin ? { Origin: origin } : {} });

test("404 and CORS", async () => {
  assert.equal((await worker.fetch(req("/nope"), env, ctx)).status, 404);
  const ok = await worker.fetch(req("/trains", "https://ok.example"), env, ctx);
  assert.equal(ok.status, 200);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), "https://ok.example");
  assert.equal(ok.headers.get("Cache-Control"), "public, max-age=15");
  assert.equal(calls[0].ua, "spain-strategy-map/1.0 (open-source map project)");
  const bad = await worker.fetch(req("/trains", "https://evil.example"), env, ctx);
  assert.equal(bad.headers.get("Access-Control-Allow-Origin"), null);
  const pre = await worker.fetch(req("/flights", "http://localhost:8799", "OPTIONS"), env, ctx);
  assert.equal(pre.status, 204);
  assert.equal(pre.headers.get("Access-Control-Allow-Origin"), "http://localhost:8799");
});

test("flights route and stale fallback", async () => {
  const f = await (await worker.fetch(req("/flights"), env, ctx)).json();
  assert.ok(f.flights.length > 0 && f.stale === false);
  // force expiry of the fresh copy, then break upstream
  const real = Date.now;
  Date.now = () => real() + 400_000; // the fresh copy lasts 360 s
  fail = true;
  try {
    const res = await worker.fetch(req("/flights"), env, ctx);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get("X-Live-Stale"), "1");
    assert.equal((await res.json()).stale, true);
  } finally { Date.now = real; fail = false; }
});

test("flights: 4 circles, the key goes only to adsb.lol and only when the secret exists", async () => {
  const real = Date.now;
  Date.now = () => real() + 800_000; // past the fresh copy
  try {
    calls.length = 0;
    await worker.fetch(req("/flights"), { ...env, ADSB_LOL_KEY: "test-key" }, ctx);
    const adsb = calls.filter((c) => c.url.includes("api.adsb.lol"));
    assert.equal(adsb.length, 4);
    assert.ok(adsb.every((c) => c.key === "test-key"));
    Date.now = () => real() + 1_600_000;
    calls.length = 0;
    await worker.fetch(req("/flights"), env, ctx);
    assert.ok(calls.filter((c) => c.url.includes("api.adsb.lol")).every((c) => c.key === undefined));
    calls.length = 0;
    await worker.fetch(req("/trains"), { ...env, ADSB_LOL_KEY: "test-key" }, ctx);
    assert.ok(calls.length > 0 && calls.every((c) => c.key === undefined));
  } finally { Date.now = real; }
});
