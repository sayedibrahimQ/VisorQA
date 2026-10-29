import { Hero } from "@/components/landing/Hero";
import { Ribbon, SiteHeader } from "@/components/landing/SiteHeader";
import {
  ArchitectureBento,
  Faq,
  FinalCta,
  Footer,
  Guardrails,
  Metrics,
  ModelStrip,
  Pipeline,
  ProductProof,
} from "@/components/landing/Sections";

export default function LandingPage() {
  return (
    <div id="top" className="min-h-screen bg-canvas text-text-primary">
      <Ribbon />
      <SiteHeader />
      <main className="mx-auto max-w-6xl px-4 pb-4 pt-10 md:pt-14">
        <Hero />
        <ModelStrip />
        <Metrics />
        <Pipeline />
        <ProductProof />
        <ArchitectureBento />
        <Guardrails />
        <Faq />
        <FinalCta />
      </main>
      <div className="mx-auto max-w-6xl px-4">
        <Footer />
      </div>
    </div>
  );
}
