import Link from "next/link";
import { Logo } from "@/components/brand/Logo";

export default function NotFound() {
  return (
    <main id="main" className="notfound-page">
      <Logo />
      <span className="mono">ERROR / 404</span>
      <h1>
        This signal
        <br />
        <em>did not arrive.</em>
      </h1>
      <p>The page you were looking for is not part of this prototype.</p>
      <div className="hero-actions">
        <Link className="button" href="/">
          Return home
        </Link>
        <Link className="button button-outline" href="/dashboard">
          Explore the demo workspace
        </Link>
      </div>
    </main>
  );
}
