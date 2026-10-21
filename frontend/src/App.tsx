import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { ModulePlaceholder } from "./components/ModulePlaceholder";
import { LibraryPage } from "./modules/library/LibraryPage";
import { LibraryProvider } from "./modules/library/LibraryContext";
import { ResearchPage } from "./modules/research/ResearchPage";
import { ResearchProvider } from "./modules/research/ResearchContext";
import { SummarizePage } from "./modules/summarize/SummarizePage";

export function App() {
  return (
    <LibraryProvider>
      <ResearchProvider>
        <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/research" replace />} />
          <Route path="/research" element={<ResearchPage />} />
          <Route path="/summarize" element={<SummarizePage />} />
          <Route path="/library" element={<LibraryPage />} />

        <Route
          path="/math"
          element={
            <ModulePlaceholder
              module={3}
              title="Pre-Calculus & Physics"
              summary="Step-by-step algebra, functions, trigonometry, limits and graphs, plus a physics toolkit."
              features={[
                "Step-by-step solver with explanations",
                "Graph plotter with intercepts, asymptotes, domain and range",
                "Physics formula sheet and solve-for-the-unknown calculator",
                "Unit converter and projectile motion simulator",
                "Practice generator with hidden answers and a score tracker",
              ]}
            />
          }
        />
        <Route
          path="/data"
          element={
            <ModulePlaceholder
              module={4}
              title="Data Analyst"
              summary="Upload Excel/CSV files for automatic cleaning, statistics, charts and an Excel formula helper."
              features={[
                "Auto-summary, data types, missing values, outliers and cleaning",
                "Descriptive stats, correlation, regression, t-test, chi-square, ANOVA",
                "Chart builder: bar, line, scatter, histogram, box, pie",
                "Plain-English Excel formula helper (SUMIF, XLOOKUP, INDEX/MATCH)",
                "Export cleaned data and charts back to Excel",
              ]}
            />
          }
        />
        <Route
          path="/biology"
          element={
            <ModulePlaceholder
              module={5}
              title="Biology Lab"
              summary="Flashcards with spaced repetition, concept explainers, genetics calculators and gene lookups."
              features={[
                "Flashcard and quiz maker with spaced repetition (SM-2)",
                "Concept explainer with key terms, analogy and a short quiz",
                "Punnett square and genetics probability calculator",
                "Gene and protein lookup via NCBI/UniProt",
                "Lab report helper with draft feedback",
              ]}
            />
          }
        />
        <Route
          path="/chat"
          element={
            <ModulePlaceholder
              module={6}
              title="AI Study Chat"
              summary="A tutor that explains, quizzes and answers questions about your saved sources."
              features={[
                "Configurable LLM provider via .env (free tier supported)",
                "Guides you with hints before revealing the full answer",
                "Answers questions about your saved research library",
                "Quiz mode with reveal-on-click",
              ]}
            />
          }
        />

          <Route path="*" element={<Navigate to="/research" replace />} />
        </Routes>
        </Layout>
      </ResearchProvider>
    </LibraryProvider>
  );
}
