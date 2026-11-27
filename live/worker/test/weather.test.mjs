import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseForecast, parseWarnings } from "../src/weather.js";
import { CITIES } from "../src/cities.js";

const raw = (n) => readFileSync(new URL(`./fixtures/${n}`, import.meta.url));
const xml = (n) => new TextDecoder("iso-8859-15").decode(raw(n));

test("parseForecast: Madrid, empty 00-24 periods fall back to first non-empty", () => {
  const f = parseForecast(xml("weather_28079.xml"));
  assert.equal(f.name, "Madrid");
  assert.equal(f.elaborado, "2026-11-27T15:59:08");
  assert.equal(f.days.length, 2);
  const [d0, d1] = f.days;
  assert.equal(d0.date, "2026-11-27");
  assert.equal(d0.tmax, 12);
  assert.equal(d0.tmin, 2);
  assert.equal(d0.rain_prob, 0); // 00-24 empty -> 06-12 is "0", not null
  assert.equal(d0.sky, "11"); // 00-24 and 00-12 empty -> 12-24
  assert.equal(d0.sky_text, "Despejado");
  assert.equal(d0.wind_dir, "C");
  assert.equal(d0.wind_kmh, 0);
  assert.equal(d1.sky, "16");
  assert.equal(d1.sky_text, "Cubierto");
  assert.equal(d1.wind_dir, "NE");
  assert.equal(d1.wind_kmh, 5);
  assert.equal(d1.tmax, 11);
});

test("parseForecast: ISO-8859-15 accents survive, Canarias parses", () => {
  const f = parseForecast(xml("weather_35016.xml"));
  assert.equal(f.name, "Palmas de Gran Canaria, Las");
  assert.equal(f.days.length, 2);
  for (const d of f.days) {
    assert.match(d.date, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(Number.isInteger(d.tmax));
    assert.ok(Number.isInteger(d.tmin));
  }
});

test("parseForecast: missing values are null, never 0", () => {
  const f = parseForecast(`<root><elaborado>2026-01-01T10:00:00</elaborado><nombre>X</nombre><prediccion>
    <dia fecha="2026-01-01"><prob_precipitacion periodo="00-24"/><estado_cielo periodo="00-24" descripcion=""/>
    <viento periodo="00-24"><direccion></direccion><velocidad></velocidad></viento>
    <temperatura><maxima></maxima><minima></minima></temperatura></dia></prediccion></root>`);
  assert.deepEqual(f.days[0], {
    date: "2026-01-01", sky: null, sky_text: null, tmax: null, tmin: null,
    rain_prob: null, wind_dir: null, wind_kmh: null,
  });
});

test("parseForecast: garbage gives empty result", () => {
  const f = parseForecast("<html>error</html>");
  assert.deepEqual(f, { name: null, elaborado: null, days: [] });
});

test("parseWarnings: real RSS", () => {
  const r = parseWarnings(readFileSync(new URL("./fixtures/weather_warnings.xml", import.meta.url), "utf8"));
  assert.equal(r.warnings_total, 6);
  assert.equal(r.warnings.length, 6);
  const w = r.warnings[0];
  assert.equal(w.level, "amarillo");
  assert.equal(w.title, "Aviso. Nivel amarillo. Lluvias. Este de La Palma");
  assert.equal(w.area, "Este de La Palma");
  assert.match(w.link, /^https:\/\/www\.aemet\.es\//);
});

test("parseWarnings: severity order, unknown level null, cap 60, entities", () => {
  const item = (t) => `<item><title>${t}</title><description>d</description><link>https://www.aemet.es/x</link></item>`;
  const items = [item("Aviso. Nivel amarillo. Nieblas. A"), item("Aviso. Nivel rojo. Costeros. B &amp; C"), item("Otra cosa")];
  for (let i = 0; i < 70; i++) items.push(item("Aviso. Nivel naranja. Viento. Z" + i));
  const r = parseWarnings(`<rss><channel>${items.join("")}</channel></rss>`);
  assert.equal(r.warnings_total, 73);
  assert.equal(r.warnings.length, 60);
  assert.equal(r.warnings[0].level, "rojo");
  assert.equal(r.warnings[0].area, "B & C");
  assert.equal(r.warnings[1].level, "naranja");
  const unk = parseWarnings(`<rss>${item("Otra cosa")}</rss>`).warnings[0];
  assert.equal(unk.level, null);
  assert.equal(unk.area, null);
});

test("CITIES: 68 unique ids, 5-digit INE codes", () => {
  assert.equal(CITIES.length, 68);
  assert.equal(new Set(CITIES.map((c) => c.id)).size, 68);
  for (const c of CITIES) assert.match(c.ine, /^\d{5}$/);
});

// Route test: fetch mocked, bytes kept in ISO-8859-15.
const store = new Map();
globalThis.caches = {
  default: {
    async match(req) { const r = store.get(req.url); return r ? r.clone() : undefined; },
    async put(req, res) { store.set(req.url, res); },
  },
};
let mode = "ok";
let active = 0, maxActive = 0;
globalThis.fetch = async (url) => {
  const u = String(url);
  active++; maxActive = Math.max(maxActive, active);
  await new Promise((r) => setTimeout(r, 1));
  active--;
  if (mode === "down") throw new Error("down");
  if (u.includes("RSS")) return new Response(raw("weather_warnings.xml"));
  const n = Number(u.match(/localidad_(\d+)/)[1]);
  if (mode === "partial" && n % 2 === 0) return new Response("nope", { status: 500 });
  return new Response(raw("weather_28079.xml"));
};
const { default: worker } = await import("../src/index.js");
const env = { ALLOWED_ORIGINS: "https://ok.example" };
const ctx = { waitUntil() {} };
const get = () => worker.fetch(new Request("https://x.test/weather", { headers: { Origin: "https://ok.example" } }), env, ctx);

test("/weather: contract, concurrency 6, CORS", async () => {
  const res = await get();
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), "https://ok.example");
  const b = await res.json();
  assert.equal(b.source, "AEMET");
  assert.equal(b.stale, false);
  assert.equal(Object.keys(b.cities).length, 68);
  assert.equal(b.cities.ES001F.ine, "28079");
  assert.equal(b.cities.ES001F.name, "Madrid");
  assert.equal(b.cities.ES001F.elaborado, "2026-11-27T15:59:08");
  assert.equal(b.cities.ES001F.days.length, 2);
  assert.equal(b.warnings_total, 6);
  assert.ok(maxActive <= 7, `concurrency ${maxActive}`); // 6 cities + 1 RSS
});

test("/weather: second call served from fresh cache (no new fetches)", async () => {
  const before = maxActive;
  mode = "down";
  const res = await get();
  assert.equal(res.status, 200);
  assert.equal((await res.json()).stale, false);
  assert.equal(before, maxActive);
});
