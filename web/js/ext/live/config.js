// Relay for the live layers (a Cloudflare Worker that adds CORS to Renfe and adsb.lol).
// Tests can point to another relay with localStorage "live_url".
export const LIVE_URL = "https://spain-strategy-map-live.daniel-l-pez.workers.dev";

// Feeds shown in the Map menu. Flights are off: adsb.lol answers 429 to Cloudflare Workers (shared egress IPs), so
// the relay cannot serve them yet.
export const ENABLED = { trains: true, flights: false };

export function liveUrl() {
  try {
    const v = localStorage.getItem("live_url");
    if (v && /^https?:\/\//.test(v)) return v.replace(/\/+$/, "");
  } catch { /* storage blocked */ }
  return LIVE_URL;
}
