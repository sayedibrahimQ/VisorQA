import React from "react";
import { PromoBanner } from "../../components/PromoBanner";
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
