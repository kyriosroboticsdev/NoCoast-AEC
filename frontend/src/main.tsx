import { createRoot } from "react-dom/client";
import App from "./App";
import "@fontsource-variable/inter";
import "./styles.css";

// No StrictMode: its double-mount would create two WebGL viewers.
createRoot(document.getElementById("root")!).render(<App />);
