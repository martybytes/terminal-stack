// Router: every page renders inside the Shell frame. HashRouter so the
// backend can serve one static index.html without a history fallback.

import { HashRouter, Route, Routes } from "react-router-dom";
import Shell from "./components/Shell";
import Dashboard from "./pages/Dashboard";
import Requests from "./pages/Requests";
import Timeline from "./pages/Timeline";
import Memories from "./pages/Memories";
import Sessions from "./pages/Sessions";
import Projects from "./pages/Projects";
import LlmCalls from "./pages/LlmCalls";
import Overview from "./pages/Overview";
import Reports from "./pages/Reports";
import Operations from "./pages/Operations";
import Help from "./pages/Help";
import { PreferencesProvider } from "./lib/preferences";

export default function App(): JSX.Element {
  return (
    <PreferencesProvider>
      <HashRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/overview" element={<Overview />} />
            <Route path="/requests" element={<Requests />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/llm" element={<LlmCalls />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/operations" element={<Operations />} />
            <Route path="/help" element={<Help />} />
            <Route path="/timeline" element={<Timeline />} />
            <Route path="/memories" element={<Memories />} />
            <Route path="/sessions" element={<Sessions />} />
          </Route>
        </Routes>
      </HashRouter>
    </PreferencesProvider>
  );
}
