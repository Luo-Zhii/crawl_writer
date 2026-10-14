import { NavLink, Outlet } from "react-router-dom";

import { useTheme } from "../hooks/useTheme";

export default function Layout() {
  const { theme, toggle } = useTheme();

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand">
            crawl_writer
          </NavLink>

          <nav className="nav">
            <NavLink to="/" end>
              Thư viện
            </NavLink>
            <NavLink to="/add">Thêm truyện</NavLink>
            <NavLink to="/jobs">Tiến trình</NavLink>
          </nav>

          <button
            type="button"
            onClick={toggle}
            className="theme-toggle"
            aria-label={theme === "dark" ? "Chuyển sang nền sáng" : "Chuyển sang nền tối"}
            title={theme === "dark" ? "Nền sáng" : "Nền tối"}
          >
            {theme === "dark" ? "☀" : "☾"}
          </button>
        </div>
      </header>

      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
