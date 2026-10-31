import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { CompositeWindow } from "./pages/Composite";
import "./styles.css";

// The composite map opens in a window of its own (5.0.0): the same page, told
// which project and map by its address, without the menu and the steps.
const q = new URLSearchParams(window.location.search);
const composite = Number(q.get("composite")) || 0;
const map = Number(q.get("map")) || 0;

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {composite && map ? <CompositeWindow projectId={composite} mapId={map} /> : <App />}
  </React.StrictMode>,
);
