import { motion } from "motion/react";
import { MessageCircle, Hash, Phone } from "lucide-react";

const channels = [
  {
    name: "Telegram",
    description: "Full bot API support with inline keyboards, scheduled messages, and group management.",
    icon: MessageCircle,
  },
  {
    name: "Discord",
    description: "Guild-scoped agents with slash commands, thread awareness, and role-based access.",
    icon: Hash,
  },
  {
    name: "WhatsApp",
    description: "Business API integration with media handling, contact resolution, and delivery receipts.",
    icon: Phone,
  },
];

export function ChannelsSection() {
  return (
    <section id="channels" className="py-20 sm:py-28">
      <div className="mx-auto max-w-[1120px] px-5 sm:px-8">
        {/* Section header */}
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
            Channels
          </p>
          <h2
            className="text-foreground tracking-tight mb-3"
            style={{ fontSize: 'clamp(1.5rem, 3vw, 2rem)', fontWeight: 600, lineHeight: 1.2 }}
          >
            One runtime, three platforms
          </h2>
          <p className="text-muted-foreground max-w-lg" style={{ lineHeight: 1.6 }}>
            Deploy once and reach users wherever they are. Each channel adapter handles 
            platform-specific nuances so your agent logic stays clean.
          </p>
        </motion.div>

        {/* Channel cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {channels.map((channel, i) => (
            <motion.div
              key={channel.name}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.45, delay: i * 0.08 }}
              className="group relative rounded-xl border border-border bg-card p-6 hover:border-border/80 hover:bg-card/80 transition-all"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-secondary">
                  <channel.icon className="h-5 w-5 text-foreground" />
                </div>
              </div>
              <h3
                className="text-foreground mb-2"
                style={{ fontSize: '1.0625rem', fontWeight: 600 }}
              >
                {channel.name}
              </h3>
              <p className="text-muted-foreground" style={{ fontSize: '0.875rem', lineHeight: 1.6 }}>
                {channel.description}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}