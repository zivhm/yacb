import { motion } from "motion/react";
import { Route, Clock, Users, Database, Puzzle } from "lucide-react";

const features = [
  {
    icon: Route,
    title: "Smart model routing",
    description:
      "Each message is classified as light, medium, or heavy and routed to the appropriate model tier. Fast responses stay fast; complex queries get the compute they need.",
    detail: "light → medium → heavy",
  },
  {
    icon: Clock,
    title: "Reliable reminders",
    description:
      "Reminders are backed by real scheduling infrastructure, not prompt hacks. They persist across restarts and fire when they should.",
    detail: "cron-backed, persistent",
  },
  {
    icon: Users,
    title: "Multi-agent mapping",
    description:
      "Assign different agent configurations per channel or chat. Each conversation gets its own context, personality, and tool access.",
    detail: "per-channel isolation",
  },
  {
    icon: Database,
    title: "Workspace memory",
    description:
      "Scoped memory stores context at the workspace level. Agents recall what matters without leaking across boundaries.",
    detail: "scoped, queryable",
  },
  {
    icon: Puzzle,
    title: "OpenClaw ecosystem",
    description:
      "Fully compatible with OpenClaw skills and extensions. Drop in existing OpenClaw skills or build new ones — the same skill interface works unchanged.",
    detail: "skills & extensions",
  },
];

export function FeaturesSection() {
  return (
    <section id="features" className="py-20 sm:py-28 border-t border-border/50">
      <div className="mx-auto max-w-[1120px] px-5 sm:px-8">
        {/* Section header */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5 }}
          className="mb-14"
        >
          <p
            className="text-accent mb-2 tracking-wide uppercase"
            style={{ fontSize: '0.75rem', fontWeight: 600, letterSpacing: '0.08em' }}
          >
            Capabilities
          </p>
          <h2
            className="text-foreground tracking-tight mb-3"
            style={{ fontSize: 'clamp(1.5rem, 3vw, 2rem)', fontWeight: 600, lineHeight: 1.2 }}
          >
            Built for daily reliability
          </h2>
          <p className="text-muted-foreground max-w-lg" style={{ lineHeight: 1.6 }}>
            Focused on reliability and compatibility — yacb runs lean, routes smart, 
            and plays well with the OpenClaw ecosystem.
          </p>
        </motion.div>

        {/* Feature grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          {features.map((feature, i) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.45, delay: i * 0.06 }}
              className={`group rounded-xl border border-border bg-card p-6 sm:p-7 hover:border-border/80 transition-all${
                i === features.length - 1 && features.length % 2 !== 0
                  ? " sm:col-span-2"
                  : ""
              }`}
            >
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-secondary">
                  <feature.icon className="h-5 w-5 text-foreground" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-3 mb-2 flex-wrap">
                    <h3
                      className="text-foreground"
                      style={{ fontSize: '1.0625rem', fontWeight: 600 }}
                    >
                      {feature.title}
                    </h3>
                    <span
                      className="text-muted-foreground/60 font-mono"
                      style={{ fontSize: '0.6875rem' }}
                    >
                      {feature.detail}
                    </span>
                  </div>
                  <p className="text-muted-foreground" style={{ fontSize: '0.875rem', lineHeight: 1.65 }}>
                    {feature.description}
                  </p>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}