interface ModulePlaceholderProps {
  module: number;
  title: string;
  summary: string;
  features: string[];
}

/** Shown for modules that are planned but not built yet (keeps navigation honest). */
export function ModulePlaceholder({ module, title, summary, features }: ModulePlaceholderProps) {
  return (
    <section className="page">
      <header className="page-header">
        <p className="eyebrow">Module {module}</p>
        <h1>{title}</h1>
        <p className="page-subtitle">{summary}</p>
      </header>

      <div className="card">
        <h2 className="card-title">Planned features</h2>
        <ul className="feature-list">
          {features.map((feature) => (
            <li key={feature}>{feature}</li>
          ))}
        </ul>
        <p className="muted">
          This module is built in a later step. Say “next” to build the following module once the
          previous one is verified.
        </p>
      </div>
    </section>
  );
}
