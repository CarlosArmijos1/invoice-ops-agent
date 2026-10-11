import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import "./index.css";
import { Dashboard } from "./pages/Dashboard";
import { InvoiceDetail } from "./pages/InvoiceDetail";
import { Invoices } from "./pages/Invoices";
import { Reports } from "./pages/Reports";
import { Review } from "./pages/Review";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/facturas" element={<Invoices />} />
            <Route path="/facturas/:id" element={<InvoiceDetail />} />
            <Route path="/revision" element={<Review />} />
            <Route path="/reportes" element={<Reports />} />
            <Route path="/reportes/:day" element={<Reports />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
