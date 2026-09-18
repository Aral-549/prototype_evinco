export function Navbar() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-bg/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <span className="font-display text-lg font-semibold tracking-tight">
          project<span className="text-accent">.</span>name
        </span>
        <nav className="hidden gap-8 text-sm text-fg-muted sm:flex">
          <a href="#work" className="transition-colors hover:text-fg">
            Product
          </a>
          <a href="#team" className="transition-colors hover:text-fg">
            Team
          </a>
          <a href="#demo" className="transition-colors hover:text-fg">
            Demo
          </a>
        </nav>
        <a
          href="#demo"
          className="panel px-4 py-2 text-sm font-medium transition-colors hover:border-accent hover:text-accent"
        >
          Try it live
        </a>
      </div>
    </header>
  );
}
