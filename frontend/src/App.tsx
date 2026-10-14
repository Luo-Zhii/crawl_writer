import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import AddNovel from "./pages/AddNovel";
import Jobs from "./pages/Jobs";
import Library from "./pages/Library";
import NotFound from "./pages/NotFound";
import NovelDetail from "./pages/NovelDetail";
import Reader from "./pages/Reader";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Library />} />
        <Route path="/add" element={<AddNovel />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/novels/:id" element={<NovelDetail />} />
        <Route path="/novels/:id/doc/:number" element={<Reader />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
