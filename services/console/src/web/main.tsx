import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { LiveProvider } from "./lib/ws";
import "./index.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("missing #root element");

createRoot(rootEl).render(
  <StrictMode>
    <LiveProvider>
      <App />
    </LiveProvider>
  </StrictMode>,
);
