import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import BacklogPage from "./pages/BacklogPage";
import JourneyPage from "./pages/JourneyPage";
import OverviewPage from "./pages/OverviewPage";
import ProblemDetailPage from "./pages/ProblemDetailPage";
import ProblemsPage from "./pages/ProblemsPage";
import ReportPage from "./pages/ReportPage";
import RunsPage from "./pages/RunsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="problems" element={<ProblemsPage />} />
          <Route path="problems/:problemId" element={<ProblemDetailPage />} />
          <Route path="journey" element={<JourneyPage />} />
          <Route path="backlog" element={<BacklogPage />} />
          <Route path="reports/:reportId" element={<ReportPage />} />
          <Route path="runs" element={<RunsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
