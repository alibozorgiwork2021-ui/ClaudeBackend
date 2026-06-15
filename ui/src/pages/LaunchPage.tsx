import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { createRun, type CreateRunBody } from "../api/client";

const FIELD = "w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-fg outline-none focus:border-primary";
const LABEL = "flex flex-col gap-1 text-xs text-muted";

export function LaunchPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState<CreateRunBody>({
    path: "",
    objective: "",
    dry_run: true,
    lang: "auto",
    provider: "anthropic",
    model: "",
    local: false,
    init: false,
    security_gate: true,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof CreateRunBody>(k: K, v: CreateRunBody[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function launch() {
    setBusy(true);
    setError(null);
    try {
      const body = { ...form, model: form.model || undefined };
      const res = await createRun(body);
      navigate(`/runs/${res.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-lg font-600">Develop a backend feature</h1>
      <p className="mb-5 text-sm text-muted">
        Runs the Planner → Coder → Verifier pipeline locally. Dry-run previews the work and writes
        nothing.
      </p>

      <div className="bento flex flex-col gap-4 p-5">
        <label className={LABEL}>
          Repository path
          <input
            className={`num ${FIELD}`}
            placeholder="/path/to/your/project"
            value={form.path}
            onChange={(e) => set("path", e.target.value)}
          />
        </label>
        <label className={LABEL}>
          Objective
          <textarea
            className={FIELD}
            rows={3}
            placeholder="Add JWT authentication to the API"
            value={form.objective}
            onChange={(e) => set("objective", e.target.value)}
          />
        </label>

        <div className="grid grid-cols-2 gap-4">
          <label className={LABEL}>
            Provider
            <select className={FIELD} value={form.provider} onChange={(e) => set("provider", e.target.value)}>
              <option value="anthropic">anthropic</option>
              <option value="ollama">ollama (local)</option>
              <option value="openai">openai</option>
            </select>
          </label>
          <label className={LABEL}>
            Language
            <select className={FIELD} value={form.lang} onChange={(e) => set("lang", e.target.value)}>
              <option value="auto">auto-detect</option>
              <option value="python">python</option>
              <option value="php">php</option>
            </select>
          </label>
        </div>

        <label className={LABEL}>
          Model (optional)
          <input
            className={`num ${FIELD}`}
            placeholder="default for provider"
            value={form.model}
            onChange={(e) => set("model", e.target.value)}
          />
        </label>

        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          {([
            ["dry_run", "Dry run (preview only)"],
            ["security_gate", "Security gate"],
            ["init", "Init repo if needed"],
            ["local", "Force local / air-gapped"],
          ] as [keyof CreateRunBody, string][]).map(([key, label]) => (
            <label key={key} className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={Boolean(form[key])}
                onChange={(e) => set(key, e.target.checked as never)}
              />
              <span className={form[key] ? "text-fg" : "text-muted"}>{label}</span>
            </label>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={launch}
            disabled={busy || !form.path || !form.objective}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-500 text-white hover:opacity-90 disabled:opacity-50 cursor-pointer"
          >
            {busy ? "Starting…" : form.dry_run ? "Preview run" : "Run"}
          </button>
          {error && <span className="text-sm text-danger">{error}</span>}
        </div>
      </div>
    </div>
  );
}
