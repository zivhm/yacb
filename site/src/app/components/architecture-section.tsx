import { motion } from "motion/react";

const flow = [
  {
    label: "Message In",
    description: "Telegram, Discord, or WhatsApp",
    color: "bg-secondary",
  },
  {
    label: "Classify",
    description: "light / medium / heavy",
    color: "bg-secondary",
  },
  {
    label: "Route",
    description: "Matched model tier",
    color: "bg-secondary",
  },
  {
    label: "Execute",
    description: "Tools, memory, response",
    color: "bg-secondary",
  },
  {
    label: "Respond",
    description: "Back to source channel",
    color: "bg-secondary",
  },
];

export function ArchitectureSection() {
  return (
    <section className="py-20 sm:py-28 border-t border-border/50">
      <div className="mx-auto max-w-[1120px] px-5 sm:px-8">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5 }}
          className="mb-12"
        >
          <p
            className="text-accent mb-2 tracking-wide uppercase"
            style={{ fontSize: '0.75rem', fontWeight: 600, letterSpacing: '0.08em' }}
          >
            How it works
          </p>
          <h2
            className="text-foreground tracking-tight mb-3"
            style={{ fontSize: 'clamp(1.5rem, 3vw, 2rem)', fontWeight: 600, lineHeight: 1.2 }}
          >
            Message lifecycle
          </h2>
          <p className="text-muted-foreground max-w-lg" style={{ lineHeight: 1.6 }}>
            Every message follows the same predictable path. No magic, no surprises.
          </p>
        </motion.div>

        {/* Flow diagram */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="rounded-xl border border-border bg-card p-6 sm:p-8"
        >
          {/* Desktop: horizontal flow */}
          <div className="hidden sm:flex items-start justify-between gap-3">
            {flow.map((step, i) => (
              <div key={step.label} className="flex items-start flex-1 min-w-0">
                <div className="flex flex-col items-center text-center flex-1">
                  <div
                    className={`${step.color} rounded-lg px-4 py-3 w-full mb-2.5 border border-border/50`}
                  >
                    <p className="text-foreground whitespace-nowrap" style={{ fontSize: '0.8125rem', fontWeight: 600 }}>
                      {step.label}
                    </p>
                  </div>
                  <p className="text-muted-foreground" style={{ fontSize: '0.75rem', lineHeight: 1.4 }}>
                    {step.description}
                  </p>
                </div>
                {i < flow.length - 1 && (
                  <div className="flex items-center pt-3.5 px-1 shrink-0">
                    <svg width="24" height="12" viewBox="0 0 24 12" className="text-muted-foreground/40">
                      <line x1="0" y1="6" x2="18" y2="6" stroke="currentColor" strokeWidth="1" />
                      <polyline points="16,2 20,6 16,10" fill="none" stroke="currentColor" strokeWidth="1" />
                    </svg>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Mobile: vertical flow */}
          <div className="sm:hidden space-y-1">
            {flow.map((step, i) => (
              <div key={step.label}>
                <div className="flex items-center gap-4">
                  <div className={`${step.color} rounded-lg px-4 py-2.5 border border-border/50 flex-1`}>
                    <p className="text-foreground" style={{ fontSize: '0.8125rem', fontWeight: 600 }}>
                      {step.label}
                    </p>
                    <p className="text-muted-foreground" style={{ fontSize: '0.6875rem' }}>
                      {step.description}
                    </p>
                  </div>
                </div>
                {i < flow.length - 1 && (
                  <div className="flex justify-start pl-6 py-0.5">
                    <div className="w-px h-4 bg-border" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  );
}