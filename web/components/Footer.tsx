export function Footer() {
  return (
    <footer className="mt-24 border-t border-ink-200 bg-white">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <div className="font-display text-xl tracking-tight">hev·shop</div>
          <p className="mt-3 max-w-xs text-sm text-ink-500">
            A store with no inventory. Every product is a 768-dimensional
            vector pretending to be a candle. Returns processed via L2 distance.
          </p>
        </div>
        <FooterCol title="Browse">
          <FooterLink href="/search?q=kitchen">Kitchen</FooterLink>
          <FooterLink href="/search?q=home">Home</FooterLink>
          <FooterLink href="/search?q=apparel">Apparel</FooterLink>
          <FooterLink href="/search?q=electronics">Electronics</FooterLink>
        </FooterCol>
        <FooterCol title="Index">
          <FooterLink href="#">CLIP ViT-L/14</FooterLink>
          <FooterLink href="#">cosine distance</FooterLink>
          <FooterLink href="#">k = 10, always</FooterLink>
        </FooterCol>
        <FooterCol title="The bit">
          <FooterLink href="#">What is a vector?</FooterLink>
          <FooterLink href="#">Why no shopping cart</FooterLink>
          <FooterLink href="#">Hire the people who made this</FooterLink>
        </FooterCol>
      </div>
      <div className="border-t border-ink-200 py-6 text-center text-xs text-ink-500">
        © {new Date().getFullYear()} hev·shop · zero items in stock · ∞ items in the latent space
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
