// CNAE-2009 section letters (nation.json industries keys "a".."u") -> the icon / emoji keys used by icons.js and the
// banners. Keys that are not a letter pass through unchanged, so older data keeps working.
const CNAE_ICON_KEY = {
  a: "agriculture", b: "mining", c: "manufacturing", d: "utilities", e: "utilities", f: "construction",
  g: "retail", h: "transportation", i: "accommodation", j: "information", k: "finance", l: "real_estate",
  m: "professional", n: "admin", o: "public_admin", p: "education", q: "health", r: "arts", s: "other",
  t: "other", u: "other",
};

export const iconKey = (k) => CNAE_ICON_KEY[String(k).toLowerCase()] || k;
