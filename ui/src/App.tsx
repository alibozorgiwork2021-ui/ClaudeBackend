import { Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { DiffPage } from "./pages/DiffPage";
import { GraphPage } from "./pages/GraphPage";
import { LaunchPage } from "./pages/LaunchPage";
import { LivePage } from "./pages/LivePage";
import { ReviewPage } from "./pages/ReviewPage";

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<LaunchPage />} />
        <Route path="/runs/:id" element={<LivePage />} />
        <Route path="/runs/:id/graph" element={<GraphPage />} />
        <Route path="/runs/:id/diff" element={<DiffPage />} />
        <Route path="/runs/:id/review" element={<ReviewPage />} />
      </Routes>
    </AppShell>
  );
}
