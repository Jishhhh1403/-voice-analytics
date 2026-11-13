import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import BacklogPage from "./pages/BacklogPage";
import DimensionDetailPage from "./pages/DimensionDetailPage";
import DimensionsPage from "./pages/DimensionsPage";
import JourneyPage from "./pages/JourneyPage";
import ProblemDetailPage from "./pages/ProblemDetailPage";
import PortfolioPage from "./pages/PortfolioPage";
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
          <Route path="dimensions" element={<DimensionsPage />} />
          <Route path="dimensions/:dimensionId" element={<DimensionDetailPage />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="problems/:problemId" element={<ProblemDetailPage />} />
          <Route path="backlog" element={<BacklogPage />} />
          <Route path="reports/:reportId" element={<ReportPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
