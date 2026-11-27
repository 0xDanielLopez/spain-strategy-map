const dec = (x, d) => x.toFixed(d).replace(".", ",");

export function compact(n) {
  if (n == null || Number.isNaN(n)) return "–";
  const a = Math.abs(n);
  if (a >= 1e12) return dec(n / 1e12, a >= 1e13 ? 1 : 2) + " bill.";
  if (a >= 1e9) return dec(n / 1e9, a >= 1e11 ? 0 : 1) + " mil M";
  if (a >= 1e6) return dec(n / 1e6, a >= 1e8 ? 0 : 1) + " M";
  if (a >= 1e3) return dec(n / 1e3, a >= 1e5 ? 0 : 1).replace(/,0$/, "") + " mil";
  return String(Math.round(n));
}

export const money = (n) => (n == null ? "–" : compact(n) + " €");
export const dollars = (n) => (n == null ? "–" : Math.round(n).toLocaleString("es-ES") + " €");
export const int = (n) => (n == null ? "–" : Math.round(n).toLocaleString("es-ES"));
export const pct = (x, d = 1) => (x == null ? "–" : (x * 100).toFixed(d).replace(".", ",") + " %");

export function yieldValue(y, v) {
  return y.unit === "usd" ? money(v) : compact(v);
}

export function popShort(n) {
  if (n >= 1e7) return Math.round(n / 1e6) + " M";
  if (n >= 1e6) return dec(n / 1e6, 1) + " M";
  return Math.round(n / 1e3) + " mil";
}

export const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
