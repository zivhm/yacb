import { useState } from "react";
import { motion } from "motion/react";
import { Copy, Check, Terminal } from "lucide-react";

const steps = [
  {
    step: 1,
    label: "Sync dependencies",
    command: "uv sync",
    detail: "Installs yacb and all dependencies into an isolated virtual environment.",
  },
  {
    step: 2,
    label: "Initialize & run",
    command: "uv run yacb init",
    detail: "Scaffolds a workspace, prompts for API keys, and starts listening on your channels.",
  },
];

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <button
      onClick={handleCopy}
      className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
      aria-label="Copy command"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

export function QuickstartSection() {
  return (
    <section id="quickstart" className="py-20 sm:py-28 border-t border-border/50">
      <div className="mx-auto max-w-[1120px] px-5 sm:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-start">
          {/* Left: description */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.5 }}
          >
            <p
              className="text-accent mb-2 tracking-wide uppercase"
              style={{ fontSize: '0.75rem', fontWeight: 600, letterSpacing: '0.08em' }}
            >
              Quickstart
            </p>
            <h2
              className="text-foreground tracking-tight mb-4"
              style={{ fontSize: 'clamp(1.5rem, 3vw, 2rem)', fontWeight: 600, lineHeight: 1.2 }}
            >
              Running in two commands
            </h2>
            <p className="text-muted-foreground mb-8" style={{ lineHeight: 1.65 }}>
              Sync your environment, then initialize. That's it — yacb is running 
              and listening on your configured channels.
            </p>

            {/* Steps */}
            <div className="space-y-5">
              {steps.map((s) => (
                <div key={s.step} className="flex items-start gap-3">
                  <div
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-secondary text-muted-foreground mt-0.5"
                    style={{ fontSize: '0.6875rem', fontWeight: 600 }}
                  >
                    {s.step}
                  </div>
                  <div>
                    <p className="text-foreground mb-0.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                      {s.label}
                    </p>
                    <p className="text-muted-foreground" style={{ fontSize: '0.8125rem' }}>
                      {s.detail}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>

          {/* Right: terminal */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ duration: 0.5, delay: 0.15 }}
          >
            <div className="rounded-xl border border-border bg-[#0e0e11] overflow-hidden">
              {/* Terminal header */}
              <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50 bg-[#0a0a0d]">
                <div className="flex gap-1.5">
                  <div className="h-2.5 w-2.5 rounded-full bg-[#2a2a30]" />
                  <div className="h-2.5 w-2.5 rounded-full bg-[#2a2a30]" />
                  <div className="h-2.5 w-2.5 rounded-full bg-[#2a2a30]" />
                </div>
                <div className="flex items-center gap-1.5 ml-3">
                  <Terminal className="h-3 w-3 text-muted-foreground/60" />
                  <span className="text-muted-foreground/60" style={{ fontSize: '0.6875rem' }}>
                    terminal
                  </span>
                </div>
              </div>

              {/* Terminal body */}
              <div className="p-5 space-y-4">
                {steps.map((s, i) => (
                  <div key={s.step}>
                    {/* Comment */}
                    <p className="text-muted-foreground/40 font-mono mb-1" style={{ fontSize: '0.75rem' }}>
                      # {s.label.toLowerCase()}
                    </p>
                    {/* Command line */}
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-accent font-mono shrink-0" style={{ fontSize: '0.8125rem' }}>
                          $
                        </span>
                        <code className="text-foreground font-mono" style={{ fontSize: '0.8125rem' }}>
                          {s.command}
                        </code>
                      </div>
                      <CopyButton text={s.command} />
                    </div>
                    {/* Output for init command */}
                    {i === 1 && (
                      <div className="mt-2 pl-5 space-y-0.5">
                        <p className="text-muted-foreground/50 font-mono" style={{ fontSize: '0.75rem' }}>
                          workspace initialized
                        </p>
                        <p className="text-emerald-400/70 font-mono" style={{ fontSize: '0.75rem' }}>
                          yacb v0.1 ready
                        </p>
                        <p className="text-muted-foreground/50 font-mono" style={{ fontSize: '0.75rem' }}>
                          telegram: connected
                        </p>
                        <p className="text-muted-foreground/50 font-mono" style={{ fontSize: '0.75rem' }}>
                          discord: connected
                        </p>
                        <p className="text-muted-foreground/50 font-mono" style={{ fontSize: '0.75rem' }}>
                          routing: light/medium/heavy
                        </p>
                        <p className="text-muted-foreground/40 font-mono" style={{ fontSize: '0.75rem' }}>
                          listening...
                        </p>
                      </div>
                    )}
                    {/* Divider between commands */}
                    {i < steps.length - 1 && <div className="border-b border-border/30 mt-3" />}
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
