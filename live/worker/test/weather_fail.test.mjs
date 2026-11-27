import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const store = new Map();
globalThis.caches = {
  default: {
    async match(req) { const r = store.get(req.url); return r ? r.clone() : undefined; },
    async put(req, res) { store.set(req.url, res); },
  },
};
const xml = readFileSync(new URL("./fixtures/weather_28079.xml", import.meta.url));
const rss = readFileSync(new URL("./fixtures/weather_warnings.xml", import.meta.url));
let mode = "partial";
globalThis.fetch = async (url) => {
  const u = String(url);
  if (mode === "down") throw new Error("down");
  if (u.includes("RSS")) return new Response(rss);
  const n = Number(u.match(/localidad_(\d+)/)[1]);
  if (mode === "partial" && n % 2 === 0) return new Response("x", { status: 500 });
  if (mode === "mostly" && n % 4 !== 1) return new Response("x", { status: 500 });
  return new Response(xml);
};
const { default: worker } = await import("../src/index.js");
const { CITIES } = await import("../src/cities.js");
const ctx = { waitUntil() {} };
const get = () => worker.fetch(new Request("https://x.test/weather"), {}, ctx);

test("no good copy and most cities failing -> 502", async () => {
  mode = "mostly";
  const odd = CITIES.filter((c) => Number(c.ine) % 4 === 1).length;
  assert.ok(odd * 2 < 68, "precondition");
  assert.equal((await get()).status, 502);
});

test("half or more answer -> 200, failed cities have days: []", async () => {
  mode = "partial";
  const ok = CITIES.filter((c) => Number(c.ine) % 2 === 1).length;
  assert.ok(ok * 2 >= 68, "precondition");
  const res = await get();
  assert.equal(res.status, 200);
  const b = await res.json();
  const bad = CITIES.find((c) => Number(c.ine) % 2 === 0);
  assert.deepEqual(b.cities[bad.id].days, []);
  assert.equal(b.cities[bad.id].elaborado, null);
});
