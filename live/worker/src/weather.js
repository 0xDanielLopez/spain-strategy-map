// Pure parsers for AEMET data (municipal forecast XML and warnings RSS).
// Regex based on purpose: Workers have no DOMParser. The technical content is
// passed through unchanged; only the shape is reduced.

const ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'" };

function decode(s) {
  return String(s)
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&(amp|lt|gt|quot|apos);/g, (m) => ENTITIES[m])
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .trim();
}

function intOrNull(s) {
  if (s == null) return null;
  const t = String(s).trim();
  if (!/^-?\d+(\.\d+)?$/.test(t)) return null;
  return Math.round(Number(t));
}

function textOrNull(s) {
  if (s == null) return null;
  const t = decode(s);
  return t === "" ? null : t;
}

// Elements of a given tag as { attrs, inner }; handles <t a="1"/> and <t>..</t>.
function elements(xml, tag) {
  const re = new RegExp(`<${tag}(\\s[^>]*?)?(?:/>|>([\\s\\S]*?)</${tag}>)`, "g");
  const out = [];
  let m;
  while ((m = re.exec(xml))) out.push({ attrs: m[1] || "", inner: m[2] == null ? "" : m[2] });
  return out;
}

function attr(attrs, name) {
  const m = new RegExp(`\\b${name}="([^"]*)"`).exec(attrs);
  return m ? decode(m[1]) : null;
}

function firstInner(xml, tag) {
  const e = elements(xml, tag)[0];
  return e ? e.inner : null;
}

// The 00-24 value if present, else the first non-empty period of the day.
function pickPeriod(list, valueOf) {
  const full = list.find((e) => attr(e.attrs, "periodo") === "00-24");
  if (full && valueOf(full) != null) return full;
  return list.find((e) => valueOf(e) != null) || null;
}

function parseDay(dia) {
  const date = attr(dia.attrs, "fecha");
  const body = dia.inner;

  const rain = pickPeriod(elements(body, "prob_precipitacion"), (e) => intOrNull(e.inner));
  const sky = pickPeriod(elements(body, "estado_cielo"), (e) => textOrNull(e.inner));
  const wind = pickPeriod(elements(body, "viento"), (e) => textOrNull(firstInner(e.inner, "velocidad")));
  const temp = firstInner(body, "temperatura");

  return {
    date,
    sky: sky ? textOrNull(sky.inner) : null,
    sky_text: sky ? textOrNull(attr(sky.attrs, "descripcion")) : null,
    tmax: temp != null ? intOrNull(firstInner(temp, "maxima")) : null,
    tmin: temp != null ? intOrNull(firstInner(temp, "minima")) : null,
    rain_prob: rain ? intOrNull(rain.inner) : null,
    wind_dir: wind ? textOrNull(firstInner(wind.inner, "direccion")) : null,
    wind_kmh: wind ? intOrNull(firstInner(wind.inner, "velocidad")) : null,
  };
}

// xmlText: already decoded (ISO-8859-15) text. Returns {name, elaborado, days}.
// days: the first two <dia> entries (today and tomorrow).
export function parseForecast(xmlText) {
  const xml = String(xmlText);
  const pred = firstInner(xml, "prediccion") || "";
  const head = xml.slice(0, xml.indexOf("<prediccion") >= 0 ? xml.indexOf("<prediccion") : xml.length);
  const elab = textOrNull(firstInner(head, "elaborado"));
  return {
    name: textOrNull(firstInner(head, "nombre")),
    // AEMET gives local time without offset; keep it as published.
    elaborado: elab && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(elab) ? elab : null,
    days: elements(pred, "dia").slice(0, 2).map(parseDay).filter((d) => d.date),
  };
}

const LEVEL_RANK = { rojo: 0, naranja: 1, amarillo: 2 };
const MAX_WARNINGS = 60;

// Item title looks like "Aviso. Nivel amarillo. Lluvias. Este de La Palma".
export function parseWarnings(rssText) {
  const items = elements(String(rssText), "item");
  const all = items.map((it, i) => {
    const title = textOrNull(firstInner(it.inner, "title")) || "";
    const desc = textOrNull(firstInner(it.inner, "description")) || "";
    const link = textOrNull(firstInner(it.inner, "link"));
    const t = /Nivel\s+(\p{L}+)\.\s*([^.]*)\.\s*(.+)$/u.exec(title);
    let level = t ? t[1].toLowerCase() : null;
    if (!level) {
      const d = /nivel\s+(\p{L}+)/iu.exec(desc);
      level = d ? d[1].toLowerCase() : null;
    }
    if (!(level in LEVEL_RANK)) level = null;
    return {
      i,
      w: { title, level, area: t ? t[3].trim() || null : null, link: link && /^https:\/\//.test(link) ? link : null },
    };
  });
  all.sort((a, b) => (LEVEL_RANK[a.w.level] ?? 3) - (LEVEL_RANK[b.w.level] ?? 3) || a.i - b.i);
  return { warnings: all.slice(0, MAX_WARNINGS).map((x) => x.w), warnings_total: items.length };
}
