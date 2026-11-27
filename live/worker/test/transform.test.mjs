import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { trainsFrom, flightsFrom, delaysFrom } from "../src/transform.js";

const fx = (n) => JSON.parse(readFileSync(new URL(`./fixtures/${n}.json`, import.meta.url), "utf8"));
const pc = fx("vehicle_positions");
const pl = fx("vehicle_positions_LD");
const tc = fx("trip_updates");
const tl = fx("trip_updates_LD");
const adsb = fx("adsb");

test("trains: contract shape", () => {
  const out = trainsFrom(pc, pl, tc, tl);
  assert.equal(out.source, "Renfe (CC BY 4.0)");
  assert.equal(out.stale, false);
  assert.ok(!Number.isNaN(Date.parse(out.updated)));
  assert.equal(out.trains.length, pc.entity.length + pl.entity.length);
  for (const t of out.trains) {
    assert.deepEqual(Object.keys(t).sort(), ["delay", "id", "label", "lat", "lon", "net", "status", "trip"]);
    assert.ok(["cercanias", "ld"].includes(t.net));
    assert.equal(typeof t.id, "string");
    assert.ok(Number.isFinite(t.lat) && Number.isFinite(t.lon));
    assert.ok(t.delay === null || Number.isInteger(t.delay));
  }
  assert.equal(new Set(out.trains.map((t) => t.id)).size, out.trains.length);
  assert.ok(out.trains.some((t) => t.net === "cercanias") && out.trains.some((t) => t.net === "ld"));
});

test("trains: updated comes from the feed header", () => {
  const out = trainsFrom(pc, pl, tc, tl, 0);
  const max = Math.max(Number(pc.header.timestamp), Number(pl.header.timestamp)) * 1000;
  assert.equal(out.updated, new Date(max).toISOString());
});

test("trains: delay from tripUpdate.delay, matched by tripId", () => {
  const delays = delaysFrom(tc);
  const out = trainsFrom(pc, pl, tc, tl);
  let checked = 0;
  for (const t of out.trains.filter((x) => x.net === "cercanias" && x.trip && delays.get(x.trip) !== undefined)) {
    assert.equal(t.delay, delays.get(t.trip));
    checked++;
  }
  assert.ok(checked > 0);
  assert.ok(out.trains.some((t) => t.delay > 0), "fixture has a delayed train");
});

test("trains: delay falls back to first stopTimeUpdate, missing stays null", () => {
  const trips = {
    entity: [
      { tripUpdate: { trip: { tripId: "A" }, stopTimeUpdate: [{ arrival: { delay: 120 } }] } },
      { tripUpdate: { trip: { tripId: "B" }, stopTimeUpdate: [{ departure: { delay: "60" } }] } },
      { tripUpdate: { trip: { tripId: "C" }, delay: 0 } },
      { tripUpdate: { trip: { tripId: "D" }, stopTimeUpdate: [{ stopId: "1" }] } },
    ],
  };
  const pos = (id, trip) => ({ id, vehicle: { trip: { tripId: trip }, position: { latitude: 40, longitude: -3 }, vehicle: { id } } });
  const out = trainsFrom({ entity: [pos("1", "A"), pos("2", "B"), pos("3", "C"), pos("4", "D"), pos("5", "Z")] }, null, trips, null);
  assert.deepEqual(out.trains.map((t) => t.delay), [120, 60, 0, null, null]);
});

test("trains: missing positions are dropped, not shown at 0,0", () => {
  const out = trainsFrom({ entity: [{ id: "x", vehicle: { vehicle: { id: "1" } } }, { id: "y", vehicle: { position: { latitude: 0, longitude: 0 }, vehicle: { id: "2" } } }] }, null, null, null);
  assert.equal(out.trains.length, 0);
});

test("flights: contract shape and no hex/registration", () => {
  const out = flightsFrom(adsb);
  assert.equal(out.source, "adsb.lol (ODbL 1.0)");
  assert.equal(out.stale, false);
  assert.ok(out.flights.length > 10);
  for (const f of out.flights) {
    assert.deepEqual(Object.keys(f).sort(), ["alt_ft", "gs_kt", "id", "lat", "lon", "track", "type"]);
    assert.match(f.id, /^[A-Z]{3}[0-9][0-9A-Z]{0,4}$/);
  }
  const text = JSON.stringify(out);
  assert.ok(!/"(r|hex)"/.test(text));
  assert.ok(!/dummy|DUMMY/.test(text));
});

test("flights: filtering and merging", () => {
  const out = flightsFrom(adsb);
  const ids = out.flights.map((f) => f.id);
  assert.ok(!ids.includes("RCH456"), "military dropped");
  assert.ok(!ids.includes("ECMXY"), "registration dropped");
  assert.ok(!ids.includes("RYR999"), "outside bounds dropped");
  assert.equal(new Set(ids).size, ids.length, "circles merged, duplicates dropped");
  assert.equal(ids.filter((i) => i === "VKG1455").length, 1);
  assert.ok(ids.includes("VLG77"), "callsign trimmed");
  const g = out.flights.find((f) => f.id === "IBE123");
  assert.equal(g.alt_ft, null, "ground -> null");
  assert.equal(out.flights.find((f) => f.id === "VLG77").alt_ft, 8000);
});

test("flights: missing fields are null, never 0", () => {
  const out = flightsFrom([{ ac: [{ hex: "z", flight: "IBE1 ", lat: 40, lon: -3 }] }]);
  assert.deepEqual(out.flights[0], { id: "IBE1", type: null, lat: 40, lon: -3, alt_ft: null, gs_kt: null, track: null });
});

test("flights: tolerates garbage input", () => {
  assert.equal(flightsFrom([null, {}, { ac: "x" }]).flights.length, 0);
});
