import { motion } from "motion/react";
import { ArrowRight, Github } from "lucide-react";
import logo from "@root-assets/claw_logo_white.svg";

export function HeroSection() {
  return (
    <section className="relative pt-32 pb-20 sm:pt-40 sm:pb-28 overflow-hidden">
      {/* Subtle grid background */}
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(#ededef 1px, transparent 1px), linear-gradient(90deg, #ededef 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }}
      />
      {/* Radial fade */}
      <div
        className="absolute inset-0"
        style={{
          background: "radial-gradient(ellipse 70% 50% at 50% 0%, rgba(212,161,94,0.06) 0%, transparent 70%)",
        }}
      />

      <div className="relative mx-auto max-w-[1120px] px-5 sm:px-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] }}
          className="max-w-3xl"
        >
          {/* Origin badge */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="mb-6"
          >
            <span
              className="inline-flex items-center gap-2 rounded-full border border-border bg-secondary/60 px-3.5 py-1.5 text-muted-foreground"
              style={{ fontSize: '0.8125rem' }}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              Born from OpenClaw
            </span>
          </motion.div>

          {/* Headline */}
          <h1
            className="text-foreground tracking-tight mb-5"
            style={{ fontSize: 'clamp(2rem, 5vw, 3.25rem)', fontWeight: 700, lineHeight: 1.1 }}
          >
            Your AI assistant runtime.{" "}
            <br className="hidden sm:block" />
            <span className="text-muted-foreground">Personal, predictable, precise.</span>
          </h1>

          {/* Subheadline */}
          <p
            className="text-muted-foreground max-w-xl mb-8"
            style={{ fontSize: 'clamp(1rem, 2vw, 1.125rem)', lineHeight: 1.65 }}
          >
            yacb routes each message to the right model, manages reminders on real schedules, 
            and works across Telegram, Discord, and WhatsApp — without the bloat.
          </p>

          {/* CTAs */}
          <div className="flex flex-col sm:flex-row gap-3">
            <a
              href="#quickstart"
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-foreground text-background px-5 py-3 hover:bg-foreground/90 transition-colors"
              style={{ fontSize: '0.9375rem', fontWeight: 500 }}
            >
              Get started
              <ArrowRight className="h-4 w-4" />
            </a>
            <a
              href="https://github.com/zivhm/yacb"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-secondary/60 px-5 py-3 text-foreground hover:bg-secondary transition-colors"
              style={{ fontSize: '0.9375rem', fontWeight: 500 }}
            >
              <Github className="h-4 w-4" />
              View on GitHub
            </a>
          </div>
        </motion.div>

        {/* Logo watermark */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.04 }}
          transition={{ duration: 1.5, delay: 0.5 }}
          className="absolute right-0 top-1/2 -translate-y-1/2 hidden lg:block pointer-events-none"
        >
          <img src={logo} alt="" className="w-[320px] h-[320px]" aria-hidden="true" />
        </motion.div>
      </div>
    </section>
  );
}
