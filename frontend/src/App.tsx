import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import BacklogPage from "./pages/BacklogPage";
import JourneyPage from "./pages/JourneyPage";
import MappingsPage from "./pages/MappingsPage";
import ProblemDetailPage from "./pages/ProblemDetailPage";
import ProblemsPage from "./pages/ProblemsPage";
import ReportPage from "./pages/ReportPage";
import ThemeMapPage from "./pages/ThemeMapPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<JourneyPage />} />
          <Route path="journey" element={<JourneyPage />} />
          <Route path="problems" element={<ProblemsPage />} />
          <Route path="themes" element={<ThemeMapPage />} />
          <Route path="mappings" element={<MappingsPage />} />
          <Route path="problems/:problemId" element={<ProblemDetailPage />} />
          <Route path="backlog" element={<BacklogPage />} />
          <Route path="reports/:reportId" element={<ReportPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
