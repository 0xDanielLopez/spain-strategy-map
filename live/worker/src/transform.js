// Pure functions that turn the upstream feeds into the public contract.
// No I/O and no dependencies, so they run in Workers and in node --test.

const CALLSIGN_RE = /^[A-Z]{3}[0-9][0-9A-Z]{0,4}$/;
const BOUNDS = { lonMin: -19.5, lonMax: 5, latMin: 26.5, latMax: 44.5 };

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const str = (v) => (typeof v === "string" && v.trim() !== "" ? v.trim() : null);

// GTFS-RT JSON encodes int64 as strings, so accept both.
function toInt(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? Math.round(n) : null;
}

function entitiesOf(feed) {
  return feed && Array.isArray(feed.entity) ? feed.entity : [];
}

// tripId -> delay in seconds. tripUpdate.delay wins, otherwise the first
// stopTimeUpdate arrival/departure delay.
export function delaysFrom(tripsFeed) {
  const map = new Map();
  for (const e of entitiesOf(tripsFeed)) {
    const tu = e && e.tripUpdate;
    const tripId = tu && tu.trip && tu.trip.tripId;
    if (!tripId) continue;
    let delay = toInt(tu.delay);
    if (delay === null && Array.isArray(tu.stopTimeUpdate)) {
      for (const st of tu.stopTimeUpdate) {
        delay = toInt(st && st.arrival && st.arrival.delay);
        if (delay === null) delay = toInt(st && st.departure && st.departure.delay);
        if (delay !== null) break;
      }
    }
    map.set(tripId, delay);
  }
  return map;
}

function trainsOfNet(net, positions, trips) {
  const delays = delaysFrom(trips);
  const out = [];
  for (const e of entitiesOf(positions)) {
    const v = e && e.vehicle;
    const p = v && v.position;
    if (!p || !isNum(p.latitude) || !isNum(p.longitude)) continue;
    if (p.latitude === 0 && p.longitude === 0) continue;
    const tripId = str(v.trip && v.trip.tripId);
    const vid = str(v.vehicle && v.vehicle.id) || str(e.id);
    if (!vid) continue;
    out.push({
      id: `${net}:${vid}`,
      net,
      lat: p.latitude,
      lon: p.longitude,
      trip: tripId,
      label: str(v.vehicle && v.vehicle.label),
      delay: tripId && delays.has(tripId) ? delays.get(tripId) : null,
      status: str(v.currentStatus),
    });
  }
  return out;
}

function headerTime(feed) {
  const t = toInt(feed && feed.header && feed.header.timestamp);
  return t && t > 0 ? t * 1000 : null;
}

export function trainsFrom(posC, posLD, tripsC, tripsLD, now = Date.now()) {
  const trains = [
    ...trainsOfNet("cercanias", posC, tripsC),
    ...trainsOfNet("ld", posLD, tripsLD),
  ];
  const ts = [headerTime(posC), headerTime(posLD)].filter((t) => t !== null);
  const updated = new Date(ts.length ? Math.max(...ts) : now).toISOString();
  return { updated, source: "Renfe (CC BY 4.0)", stale: false, trains };
}

export function flightsFrom(responses, now = Date.now()) {
  const byHex = new Map(); // internal dedupe only, never exposed
  for (const r of responses || []) {
    const list = r && Array.isArray(r.ac) ? r.ac : [];
    for (const a of list) {
      if (!a || !isNum(a.lat) || !isNum(a.lon)) continue;
      const key = a.hex || `${a.flight}|${a.lat}|${a.lon}`;
      if (!byHex.has(key)) byHex.set(key, a);
    }
  }
  const flights = [];
  const ids = new Set(); // a callsign is unique in the output
  for (const a of byHex.values()) {
    if ((Number(a.dbFlags) || 0) & 1) continue; // military
    const callsign = typeof a.flight === "string" ? a.flight.trim().toUpperCase() : "";
    if (!CALLSIGN_RE.test(callsign) || ids.has(callsign)) continue;
    if (a.lon < BOUNDS.lonMin || a.lon > BOUNDS.lonMax) continue;
    if (a.lat < BOUNDS.latMin || a.lat > BOUNDS.latMax) continue;
    ids.add(callsign);
    flights.push({
      id: callsign,
      type: str(a.t),
      lat: a.lat,
      lon: a.lon,
      alt_ft: a.alt_baro === "ground" ? null : isNum(a.alt_baro) ? Math.round(a.alt_baro) : null,
      gs_kt: isNum(a.gs) ? a.gs : null,
      track: isNum(a.track) ? a.track : null,
    });
  }
  return {
    updated: new Date(now).toISOString(),
    source: "adsb.lol (ODbL 1.0)",
    stale: false,
    flights,
  };
}
