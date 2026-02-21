import { useState } from "react";
import { Menu, X, Github } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import logo from "@root-assets/claw_logo_white.svg";

const navLinks = [
  { label: "Features", href: "#features" },
  { label: "Quickstart", href: "#quickstart" },
  { label: "Channels", href: "#channels" },
  { label: "Docs", href: "https://github.com/zivhm/yacb#readme" },
];

export function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-xl">
      <div className="mx-auto max-w-[1120px] px-5 sm:px-8">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <a href="#" className="flex items-center gap-2.5">
            <img src={logo} alt="yacb logo" className="h-7 w-7" />
            <span className="text-foreground tracking-tight" style={{ fontWeight: 600, fontSize: '1.125rem' }}>
              yacb
            </span>
          </a>

          {/* Desktop Links */}
          <div className="hidden md:flex items-center gap-8">
            {navLinks.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="text-muted-foreground hover:text-foreground transition-colors"
                style={{ fontSize: '0.875rem' }}
              >
                {link.label}
              </a>
            ))}
          </div>

          {/* GitHub Button */}
          <div className="hidden md:flex items-center gap-3">
            <a
              href="https://github.com/zivhm/yacb"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg border border-border bg-secondary px-4 py-2 text-foreground hover:bg-border transition-colors"
              style={{ fontSize: '0.875rem' }}
            >
              <Github className="h-4 w-4" />
              GitHub
            </a>
          </div>

          {/* Mobile toggle */}
          <button
            className="md:hidden text-muted-foreground hover:text-foreground"
            onClick={() => setMobileOpen(!mobileOpen)}
            aria-label="Toggle menu"
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Menu */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="md:hidden border-t border-border bg-background overflow-hidden"
          >
            <div className="px-5 py-4 flex flex-col gap-3">
              {navLinks.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  className="text-muted-foreground hover:text-foreground transition-colors py-2"
                  style={{ fontSize: '0.875rem' }}
                  onClick={() => setMobileOpen(false)}
                >
                  {link.label}
                </a>
              ))}
              <a
                href="https://github.com/zivhm/yacb"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 rounded-lg border border-border bg-secondary px-4 py-2.5 text-foreground hover:bg-border transition-colors mt-2 w-fit"
                style={{ fontSize: '0.875rem' }}
              >
                <Github className="h-4 w-4" />
                GitHub
              </a>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </nav>
  );
}
