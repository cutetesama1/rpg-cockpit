import "./modelVoice.css";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import MultiplayerApp from "./MultiplayerApp";
import "./styles.css";
import "./artTheme.css";
import "./mobileChat.css";
import "./uiThemes.css";
import "./mobileComposer.css";
import "./corrections.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {new URLSearchParams(location.search).get("multiplayer")==="1" ? <MultiplayerApp/> : <App />}
  </React.StrictMode>,
);
