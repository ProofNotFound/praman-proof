import { BrowserRouter, Route, Routes } from "react-router";
import { AppProvider, useApp, useOpenCase } from "./AppContext";
import { useKeys } from "./hooks/useKeys";
import { SvgDefs } from "./components/Seal";
import { ShortcutSheet } from "./components/ShortcutSheet";
import { IntakeRoute } from "./routes/Intake";
import { CaseRoute } from "./routes/Case";
import { ReportRoute } from "./routes/Report";
import { EvalRoute } from "./routes/Eval";
import { ScanRoute } from "./routes/Scan";
import { ImpactRoute } from "./routes/Impact";
import { RulesRoute } from "./routes/Rules";

function GlobalKeys() {
  const { demoCases, present, setPresent, shortcuts, setShortcuts } = useApp();
  const openCase = useOpenCase();
  const open = (i: number) => () => {
    const c = demoCases[i];
    if (c) void openCase(c.listingId);
  };
  useKeys({
    "1": open(0),
    "2": open(1),
    "3": open(2),
    "4": open(3),
    p: () => setPresent(!present),
    "?": () => setShortcuts(!shortcuts),
  });
  return shortcuts ? <ShortcutSheet onClose={() => setShortcuts(false)} /> : null;
}

export function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <SvgDefs />
        <GlobalKeys />
        <Routes>
          <Route path="/" element={<IntakeRoute />} />
          <Route path="/case/:caseId" element={<CaseRoute />} />
          <Route path="/case/:caseId/report" element={<ReportRoute />} />
          <Route path="/eval" element={<EvalRoute />} />
          <Route path="/impact" element={<ImpactRoute />} />
          <Route path="/rules" element={<RulesRoute />} />
          <Route path="/scan" element={<ScanRoute />} />
          <Route path="/scan/:scanId" element={<ScanRoute />} />
          <Route path="*" element={<IntakeRoute />} />
        </Routes>
        <div className="grain" aria-hidden="true" />
      </AppProvider>
    </BrowserRouter>
  );
}
