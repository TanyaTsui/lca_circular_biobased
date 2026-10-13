// Worked examples for the "Load a case" picker. Each preset mirrors the shape of an
// exported inputs file: { today: { inputs }, future?: { inputs }, background }.
// Material names / sources are canonical values (e.g. "co-product", "Hard wood") — the
// UI relabels them for display.

const RAW_PRESETS = [
  {
    id: "biopol",
    name: "Biopolymer 3D printing",
    blurb: "Pea-protein-bound sawdust and seagrass, extrusion-printed and oven-cured. Includes an optimised high-throughput future line to compare against.",
    background: { scenarioLabel: "image_SSP2-L_2050", t: 0 },
    today: {
      inputs: {
        productKg: 1,
        productionBom: [
          { material: "Pea protein binder", pct: 70, source: "virgin" },
          { material: "Sawdust", pct: 20, source: "co-product" },
          { material: "Seagrass", pct: 10, source: "wild-harvested" },
        ],
        productionChain: [
          { name: "Milling", kgMachine: 65, powerKW: 3, rateKgHr: 1, lifetimeHrs: 20000, elecLoc: "NL", retainedPct: 100, machineSource: "virgin" },
          { name: "Mixing", kgMachine: 150, powerKW: 1.5, rateKgHr: 10, lifetimeHrs: 20000, elecLoc: "NL", retainedPct: 100, machineSource: "virgin" },
          { name: "3D printing", kgMachine: 1000, powerKW: 0.4, rateKgHr: 0.875, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 100, machineSource: "virgin" },
          { name: "Baking", kgMachine: 400, powerKW: 5, rateKgHr: 1.75, lifetimeHrs: 20000, elecLoc: "NL", retainedPct: 70, machineSource: "virgin" },
        ],
        repair: { enabled: true, repairMaterialPctOfProduct: 10, expectedLifetimeYr: 20, extensionPerRepairYr: 10, numRepairs: 3 },
        repairBom: [
          { material: "Pea protein binder", pct: 80, source: "virgin" },
          { material: "Seagrass", pct: 10, source: "wild-harvested" },
          { material: "Hemp fiber", pct: 10, source: "virgin" },
        ],
        repairChain: [
          { name: "Mixing", kgMachine: 80, powerKW: 1.5, rateKgHr: 15, lifetimeHrs: 15000, elecLoc: "NL", retainedPct: 98, machineSource: "virgin" },
          { name: "3D printing", kgMachine: 250, powerKW: 2.5, rateKgHr: 0.5, lifetimeHrs: 20000, elecLoc: "NL", retainedPct: 92, machineSource: "virgin" },
        ],
        eol: { composted: 30, recycledOpen: 20, recycledClosed: 30, incinerated: 10, landfilled: 10, disposalElecLoc: "NL" },
      },
    },
    future: {
      inputs: {
        productKg: 1,
        productionBom: [
          { material: "Pea protein binder", pct: 70, source: "virgin" },
          { material: "Sawdust", pct: 20, source: "co-product" },
          { material: "Seagrass", pct: 10, source: "wild-harvested" },
        ],
        productionChain: [
          { name: "Milling", kgMachine: 1500, powerKW: 30, rateKgHr: 250, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 100, machineSource: "virgin" },
          { name: "Mixing", kgMachine: 800, powerKW: 15, rateKgHr: 150, lifetimeHrs: 40000, elecLoc: "NL", retainedPct: 100, machineSource: "virgin" },
          { name: "3D printing", kgMachine: 2500, powerKW: 2, rateKgHr: 8, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 100, machineSource: "virgin" },
          { name: "Baking", kgMachine: 6000, powerKW: 25, rateKgHr: 35, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 70, machineSource: "virgin" },
        ],
        repair: { enabled: true, repairMaterialPctOfProduct: 10, expectedLifetimeYr: 20, extensionPerRepairYr: 10, numRepairs: 3 },
        repairBom: [
          { material: "Pea protein binder", pct: 80, source: "virgin" },
          { material: "Seagrass", pct: 10, source: "wild-harvested" },
          { material: "Hemp fiber", pct: 10, source: "virgin" },
        ],
        repairChain: [
          { name: "Mixing", kgMachine: 80, powerKW: 1.5, rateKgHr: 15, lifetimeHrs: 15000, elecLoc: "NL", retainedPct: 98, machineSource: "virgin" },
          { name: "3D printing", kgMachine: 250, powerKW: 2.5, rateKgHr: 0.5, lifetimeHrs: 20000, elecLoc: "NL", retainedPct: 92, machineSource: "virgin" },
        ],
        eol: { composted: 30, recycledOpen: 20, recycledClosed: 30, incinerated: 10, landfilled: 10, disposalElecLoc: "NL" },
      },
    },
  },

  {
    id: "timber",
    name: "Reclaimed hardwood CNC",
    blurb: "100% recycled hardwood, laser-scanned and CNC-milled to shape. Carbon-storage dominated — a strongly net-negative baseline.",
    background: { scenarioLabel: "image_SSP2-L_2050", t: 0 },
    today: {
      inputs: {
        productKg: 1,
        productionBom: [
          { material: "Hard wood", pct: 100, source: "recycled" },
        ],
        productionChain: [
          { name: "Scanning", kgMachine: 2000, powerKW: 10, rateKgHr: 600, lifetimeHrs: 40000, elecLoc: "NL", retainedPct: 100, machineSource: "virgin" },
          { name: "Milling", kgMachine: 1200, powerKW: 10, rateKgHr: 30, lifetimeHrs: 40000, elecLoc: "NL", retainedPct: 90, machineSource: "virgin" },
        ],
        repair: { enabled: true, repairMaterialPctOfProduct: 10, expectedLifetimeYr: 50, extensionPerRepairYr: 10, numRepairs: 2 },
        repairBom: [
          { material: "Hard wood", pct: 100, source: "recycled" },
        ],
        repairChain: [
          { name: "Scanning", kgMachine: 2000, powerKW: 10, rateKgHr: 600, lifetimeHrs: 40000, elecLoc: "NL", retainedPct: 100, machineSource: "virgin" },
          { name: "CNC milling", kgMachine: 1200, powerKW: 10, rateKgHr: 30, lifetimeHrs: 40000, elecLoc: "NL", retainedPct: 90, machineSource: "virgin" },
        ],
        eol: { composted: 0, recycledOpen: 0, recycledClosed: 20, incinerated: 80, landfilled: 0, disposalElecLoc: "NL" },
      },
    },
  },

  {
    id: "knit_hemp",
    name: "Knitted hemp fibre",
    blurb: "Virgin hemp fibre carded, roved, spun and knitted to near-net shape. Closed-loop recycled at end of life.",
    background: { scenarioLabel: "image_SSP2-L_2050", t: 0 },
    today: {
      inputs: {
        productKg: 1,
        productionBom: [
          { material: "Hemp fiber", pct: 100, source: "virgin" },
        ],
        productionChain: [
          { name: "Carding & roving", kgMachine: 3000, powerKW: 12, rateKgHr: 15, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 85, machineSource: "virgin" },
          { name: "Spinning", kgMachine: 800, powerKW: 5, rateKgHr: 8, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 98, machineSource: "virgin" },
          { name: "Knitting", kgMachine: 1500, powerKW: 4, rateKgHr: 2, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 98, machineSource: "virgin" },
        ],
        repair: { enabled: true, repairMaterialPctOfProduct: 10, expectedLifetimeYr: 15, extensionPerRepairYr: 10, numRepairs: 1 },
        repairBom: [
          { material: "Hemp fiber", pct: 100, source: "virgin" },
        ],
        repairChain: [
          { name: "Carding & roving", kgMachine: 3000, powerKW: 12, rateKgHr: 15, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 85, machineSource: "virgin" },
          { name: "Spinning", kgMachine: 800, powerKW: 5, rateKgHr: 8, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 98, machineSource: "virgin" },
          { name: "Knitting", kgMachine: 1500, powerKW: 4, rateKgHr: 2, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 98, machineSource: "virgin" },
        ],
        eol: { composted: 0, recycledOpen: 0, recycledClosed: 80, incinerated: 20, landfilled: 0, disposalElecLoc: "NL" },
      },
    },
  },

  {
    id: "coreless_winding",
    name: "Coreless filament winding",
    blurb: "Hemp roving wet-wound with epoxy resin into a coreless structural member. Resin-heavy footprint, incineration-dominated end of life.",
    background: { scenarioLabel: "image_SSP2-L_2050", t: 0 },
    today: {
      inputs: {
        productKg: 1,
        productionBom: [
          { material: "Hemp fiber", pct: 60, source: "virgin" },
          { material: "Fiber glue (epoxy resin)", pct: 40, source: "virgin" },
        ],
        productionChain: [
          { name: "Rope production", kgMachine: 800, powerKW: 3, rateKgHr: 20, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 95, machineSource: "virgin" },
          { name: "Wet winding", kgMachine: 3000, powerKW: 6, rateKgHr: 4, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 95, machineSource: "virgin" },
        ],
        repair: { enabled: true, repairMaterialPctOfProduct: 10, expectedLifetimeYr: 50, extensionPerRepairYr: 10, numRepairs: 3 },
        repairBom: [
          { material: "Hemp fiber", pct: 60, source: "virgin" },
          { material: "Fiber glue (epoxy resin)", pct: 40, source: "virgin" },
        ],
        repairChain: [
          { name: "Rope production", kgMachine: 800, powerKW: 3, rateKgHr: 20, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 95, machineSource: "virgin" },
          { name: "Wet winding", kgMachine: 3000, powerKW: 6, rateKgHr: 4, lifetimeHrs: 50000, elecLoc: "NL", retainedPct: 95, machineSource: "virgin" },
        ],
        eol: { composted: 0, recycledOpen: 0, recycledClosed: 20, incinerated: 80, landfilled: 0, disposalElecLoc: "NL" },
      },
    },
  },
];
