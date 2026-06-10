import { backendEnabled, backendMeta } from "@/lib/backend";
import { PRODUCTS } from "@/lib/mock-data";

const DOCS = "https://hevlayer.com/docs";

// Real vector count for the bottom line. Demo mode counts the mock catalog;
// a live backend error renders the line without a count rather than lying.
async function vectorCount(): Promise<number | null> {
  if (!backendEnabled()) return PRODUCTS.length;
  try {
    const meta = await backendMeta();
    return meta.vectors;
  } catch {
    return null;
  }
}

export async function Footer() {
  const vectors = await vectorCount();
  return (
    <footer className="mt-24 border-t border-ink-200 bg-white">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <div className="font-display text-xl tracking-tight">hev·shop</div>
          <p className="mt-3 max-w-xs text-sm text-ink-500">
            A complete open-source e-commerce search experience — image
            search, hybrid search, pipelines, and UDFs, running on{" "}
            <a
              href="https://hevlayer.com"
              className="font-medium text-ink-700 hover:text-ink-900"
            >
              hev layer
            </a>
            .
          </p>
        </div>
        <FooterCol title="Learn">
          <FooterLink href="https://github.com/hev/shop">Source on GitHub</FooterLink>
          <FooterLink href={`${DOCS}/concepts`}>Concepts</FooterLink>
          <FooterLink href={`${DOCS}/document-model`}>Document model</FooterLink>
          <FooterLink href={`${DOCS}/pipelines`}>Pipelines</FooterLink>
          <FooterLink href={`${DOCS}/udfs`}>UDFs</FooterLink>
        </FooterCol>
        <FooterCol title="Search features">
          <FooterLink href={`${DOCS}/api/query`}>Vector query</FooterLink>
          <FooterLink href={`${DOCS}/api/scans`}>Result counts</FooterLink>
          <FooterLink href={`${DOCS}/api/search-history`}>Search history</FooterLink>
          <FooterLink href={`${DOCS}/api/snapshots`}>Snapshots</FooterLink>
          <FooterLink href={`${DOCS}/api/warm-cache`}>Cache warming</FooterLink>
        </FooterCol>
        <FooterCol title="Stack">
          <FooterLink href="https://hevlayer.com">hev layer</FooterLink>
          <FooterLink href="https://turbopuffer.com">turbopuffer</FooterLink>
          <FooterLink href="https://huggingface.co/openai/clip-vit-large-patch14">
            CLIP ViT-L/14
          </FooterLink>
          <FooterLink href="https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023">
            Amazon Reviews 2023
          </FooterLink>
        </FooterCol>
      </div>
      <div className="border-t border-ink-200 py-6 text-center text-xs text-ink-500">
        © {new Date().getFullYear()} hev·shop · zero items in stock
        {vectors !== null ? (
          <> · {vectors.toLocaleString()} vectors in the latent space</>
        ) : null}{" "}
        · created by{" "}
        <a
          href="https://hevmind.com"
          className="font-medium text-ink-700 hover:text-ink-900"
        >
          hevmind
        </a>
      </div>
    </footer>
  );
}

function FooterCol({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-3 text-xs font-semibold uppercase tracking-widest text-ink-500">
        {title}
      </div>
      <ul className="space-y-2 text-sm text-ink-700">{children}</ul>
    </div>
  );
}

function FooterLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <li>
      <a href={href} className="hover:text-ink-900">
        {children}
      </a>
    </li>
  );
}
