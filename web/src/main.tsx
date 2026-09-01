import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { registerSW } from "virtual:pwa-register";
import { App } from "./App";
import "./style.css";
registerSW({ immediate: false });
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
