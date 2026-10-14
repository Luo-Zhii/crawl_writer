import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <section>
      <h1>Không có trang này</h1>
      <p className="muted">
        Về <Link to="/">thư viện</Link>.
      </p>
    </section>
  );
}
