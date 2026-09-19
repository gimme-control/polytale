import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

try {
  const m = localStorage.getItem("polytale.motion");
  if (m === "reduced" || m === "full") document.documentElement.dataset.motion = m;
} catch {
  /* storage blocked */
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
