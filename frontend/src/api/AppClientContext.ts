import { createContext } from "react";
import type { AppClient } from "./AppClient";

export const AppClientContext = createContext<AppClient | null>(null);
