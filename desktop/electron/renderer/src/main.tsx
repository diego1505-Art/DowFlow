import React from "react";
import { createRoot } from "react-dom/client";
import MusicApp from "./MusicApp";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Music renderer root is missing");

createRoot(root).render(
  <React.StrictMode>
    <MusicApp />
  </React.StrictMode>,
);
