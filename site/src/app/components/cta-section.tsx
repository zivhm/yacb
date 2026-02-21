import { motion } from "motion/react";
import { ArrowRight, BookOpen } from "lucide-react";

export function CtaSection() {
  return (
    <section className="py-20 sm:py-28 border-t border-border/50">
      <div className="mx-auto max-w-[1120px] px-5 sm:px-8">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5 }}
          className="relative rounded-2xl border border-border bg-card p-8 sm:p-12 text-center overflow-hidden"
        >
          {/* Subtle gradient accent */}
          <div
            className="absolute inset-0 opacity-[0.04] pointer-events-none"
            style={{
              background: "radial-gradient(ellipse 60% 60% at 50% 40%, #d4a15e, transparent)",
            }}
          />

          <div className="relative">
            <h2
              className="text-foreground tracking-tight mb-3"
              style={{ fontSize: 'clamp(1.5rem, 3vw, 2rem)', fontWeight: 600, lineHeight: 1.2 }}
            >
              Ready to simplify your AI stack?
            </h2>
            <p
              className="text-muted-foreground max-w-md mx-auto mb-8"
              style={{ lineHeight: 1.6 }}
            >
              yacb is open source and built for individual developers who want 
              an assistant that just works.
            </p>

            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <a
                href="#quickstart"
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-foreground text-background px-5 py-3 hover:bg-foreground/90 transition-colors"
                style={{ fontSize: '0.9375rem', fontWeight: 500 }}
              >
                Get started
                <ArrowRight className="h-4 w-4" />
              </a>
              <a
                href="https://github.com/zivhm/yacb#readme"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-secondary/60 px-5 py-3 text-foreground hover:bg-secondary transition-colors"
                style={{ fontSize: '0.9375rem', fontWeight: 500 }}
              >
                <BookOpen className="h-4 w-4" />
                Read the docs
              </a>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
