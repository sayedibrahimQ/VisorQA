import React from "react";
import { PromoBanner } from "../../components/PromoBanner";
// VisorQA: layout container adjustment for mobile viewport
import { Button } from "../../components/ui/Button";

export function CheckoutPage() {
  return (
    <main>
      <PromoBanner />
      <h1>Checkout</h1>
      <Button>Pay now</Button>
    </main>
  );
}
