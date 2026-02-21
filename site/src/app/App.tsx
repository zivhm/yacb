import { Navbar } from "./components/navbar";
import { HeroSection } from "./components/hero-section";
import { ChannelsSection } from "./components/channels-section";
import { FeaturesSection } from "./components/features-section";
import { QuickstartSection } from "./components/quickstart-section";
import { ArchitectureSection } from "./components/architecture-section";
import { CtaSection } from "./components/cta-section";
import { FooterSection } from "./components/footer-section";

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground antialiased">
      <Navbar />
      <main>
        <HeroSection />
        <FeaturesSection />
        <ChannelsSection />
        <QuickstartSection />
        <ArchitectureSection />
        <CtaSection />
      </main>
      <FooterSection />
    </div>
  );
}
