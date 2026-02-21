import { Github, ExternalLink } from "lucide-react";
import logo from "@root-assets/claw_logo_white.svg";

const links = [
  { label: "GitHub", href: "https://github.com/zivhm/yacb", external: true },
  { label: "Documentation", href: "https://github.com/zivhm/yacb#readme", external: true },
  { label: "Issues", href: "https://github.com/zivhm/yacb/issues", external: true },
  { label: "OpenClaw", href: "https://github.com/zivhm", external: true },
];

export function FooterSection() {
  return (
    <footer className="border-t border-border/50 py-12 sm:py-16">
      <div className="mx-auto max-w-[1120px] px-5 sm:px-8">
        <div className="flex flex-col sm:flex-row items-start justify-between gap-8">
          {/* Left */}
          <div>
            <div className="flex items-center gap-2.5 mb-3">
              <img src={logo} alt="yacb logo" className="h-5 w-5" />
              <span className="text-foreground" style={{ fontWeight: 600, fontSize: '0.9375rem' }}>
                yacb
              </span>
            </div>
            <p className="text-muted-foreground max-w-xs" style={{ fontSize: '0.8125rem', lineHeight: 1.6 }}>
              Yet another Claude bot — personal AI assistant runtime for people who 
              value predictability over novelty.
            </p>
          </div>

          {/* Right: links */}
          <div className="flex flex-wrap gap-x-8 gap-y-2">
            {links.map((link) => (
              <a
                key={link.label}
                href={link.href}
                target={link.external ? "_blank" : undefined}
                rel={link.external ? "noopener noreferrer" : undefined}
                className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
                style={{ fontSize: '0.8125rem' }}
              >
                {link.label}
                {link.external && <ExternalLink className="h-3 w-3" />}
              </a>
            ))}
          </div>
        </div>

        {/* Bottom bar */}
        <div className="mt-10 pt-6 border-t border-border/30 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-muted-foreground/60" style={{ fontSize: '0.75rem' }}>
            MIT License
          </p>
          <a
            href="https://github.com/zivhm/yacb"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-muted-foreground/60 hover:text-muted-foreground transition-colors"
            style={{ fontSize: '0.75rem' }}
          >
            <Github className="h-3.5 w-3.5" />
            zivhm/yacb
          </a>
        </div>
      </div>
    </footer>
  );
}
