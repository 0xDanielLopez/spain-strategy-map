// lon/lat -> map km, an exact port of pipeline/core/geo.py MapProjection (main Albers + Canarias inset).
// Constants come from web/data/projection.json (pipeline/build/projection.py).
//   createProjection(doc) -> {project(lon, lat) -> [x, y], hidden(lon, lat) -> bool}
import { dataBase } from "../app/scope.js";
const RAD = Math.PI / 180;

function albers(lat1, lat2, lat0, lon0, R) {
  const p1 = lat1 * RAD, p2 = lat2 * RAD, p0 = lat0 * RAD;
  const l0 = lon0 * RAD;
  const n = (Math.sin(p1) + Math.sin(p2)) / 2;
  const c = Math.cos(p1) ** 2 + 2 * n * Math.sin(p1);
  const rho0 = (R * Math.sqrt(c - 2 * n * Math.sin(p0))) / n;
  return (lon, lat) => {
    const rho = (R * Math.sqrt(c - 2 * n * Math.sin(lat * RAD))) / n;
    const theta = n * (lon * RAD - l0);
    return [rho * Math.sin(theta), rho0 - rho * Math.cos(theta)];
  };
}

export function createProjection(doc) {
  const R = doc.r_earth_km;
  const main = albers(...doc.main_albers, R);
  const insets = doc.insets.map((i) => ({ ...i, proj: albers(...i.albers, R) }));
  const regionOf = (lon, lat) => insets.find((i) => i.box[0] <= lon && lon <= i.box[2] && i.box[1] <= lat && lat <= i.box[3]) || null;
  const inFrame = (i, x, y) => i.frame[0] <= x && x <= i.frame[2] && i.frame[1] <= y && y <= i.frame[3];
  const insetXY = (i, lon, lat) => {
    const [x, y] = i.proj(lon, lat);
    return [x + i.tx, y + i.ty];
  };
  const shift = (x, y) => [x - doc.min_x + doc.margin, doc.max_y - y + doc.margin];
  function project(lon, lat) {
    const ins = regionOf(lon, lat);
    const [x, y] = ins ? insetXY(ins, lon, lat) : main(lon, lat);
    return shift(x, y);
  }
  function hidden(lon, lat) {
    const ins = regionOf(lon, lat);
    if (ins) return !inFrame(ins, ...insetXY(ins, lon, lat));
    const [x, y] = main(lon, lat);
    return insets.some((i) => inFrame(i, x, y));
  }
  return { project, hidden };
}

let loaded = null;
/** Fetch projection.json once and build the projection (rejects if the file is missing). */
export function loadProjection(url = `${dataBase()}projection.json`) {
  loaded ??= fetch(url).then((r) => {
    if (!r.ok) throw new Error(`projection.json: HTTP ${r.status}`);
    return r.json();
  }).then(createProjection);
  loaded.catch(() => { loaded = null; });
  return loaded;
}
