// Map-art extension: tile improvements (autovías y carreteras principales, ferrocarril, puertos, aeropuertos) and
// "Patrimonio y parques" (Patrimonio mundial and Parques nacionales), each as a static layer drawn into the cached
// map (nothing animates; an idle map draws no frames), with a switch in the "Mapa" menu.
//
// Data: infrastructure.json and wonders.json (loaded by main.js right after the first frame; app.loadData returns the
// same promise). A switch is registered only when its file exists and has items; a missing file leaves it out.
// Spain has no military.json, trade.json or disasters.json: those layers have no switch and are never requested here
// (the model still accepts them, so a later build can add them by listing them in TOGGLES and DATA_FILES).
import { createModel } from "./model.js";
import { makeLayers } from "./layers.js";
import { tips } from "./tips.js";

// has(data) = the file holds something to draw. Resources are the "Recursos" switch of the main toolbar.
const TOGGLES = [
  { id: "roads", label: "Carreteras", icon: "t-road", def: true, title: "Autopistas, autovías y carreteras principales (Natural Earth, como arte del mapa)", layers: ["roads"], file: "infrastructure", has: (d) => d?.roads?.length > 0 },
  { id: "rail", label: "Ferrocarril", icon: "t-rail", def: true, title: "Líneas ferroviarias principales y secundarias (Natural Earth, como arte del mapa)", layers: ["rail"], file: "infrastructure", has: (d) => d?.rail?.length > 0 },
  { id: "hubs", label: "Puertos y aeropuertos", icon: "d-harbor", def: true, title: "Puertos principales (Natural Earth) y aeropuertos principales (OurAirports); sin cifras de tráfico", layers: ["hubs"], file: "infrastructure", has: (d) => d?.ports?.length > 0 || d?.airports?.length > 0 },
  { id: "wonders", label: "Patrimonio y parques", icon: "w-landmark", def: true, title: "Bienes del Patrimonio mundial y parques nacionales", layers: ["wonders", "protected", "plates"], file: "wonders", has: (d) => d?.wonders?.length > 0 },
];
const DATA_FILES = ["infrastructure", "wonders"];

export function install(app) {
  const model = createModel(app.w);
  const on = Object.fromEntries(TOGGLES.map((t) => [t.id, t.def]));
  const layers = makeLayers(model, on, { tips, app });
  for (const l of layers) app.registerStaticLayer(l);

  const added = new Set();
  const addToggles = (name, data) => {
    for (const t of TOGGLES) {
      if (t.file !== name || added.has(t.id) || !t.has(data)) continue;
      added.add(t.id);
      app.ui.addMapToggle({
        id: t.id, label: t.label, icon: t.icon, title: t.title, default: t.def,
        get: () => on[t.id],
        set: (v) => {
          on[t.id] = !!v;
          app.requestDraw();
        },
      });
    }
  };
  const apply = (name, data) => {
    model.setData(name, data);
    if (data) addToggles(name, data);
    app.requestDraw();
  };
  for (const name of DATA_FILES) {
    if (app.data[name] !== undefined) apply(name, app.data[name]);
    else app.loadData(name).then((d) => apply(name, d), (err) => console.warn(`map layers: ${name} failed to load`, err));
  }

  // For debugging and the gallery: the model and switches.
  app.mapArt = { model, on, layers };
}
