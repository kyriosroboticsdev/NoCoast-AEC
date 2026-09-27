import { createRoot } from "react-dom/client";
import App from "./App";
import "@fontsource-variable/inter";
import "./styles.css";
import { applyTheme, initialTheme } from "./state/theme";

applyTheme(initialTheme());

// No StrictMode: its double-mount would create two WebGL viewers.
createRoot(document.getElementById("root")!).render(<App />);
