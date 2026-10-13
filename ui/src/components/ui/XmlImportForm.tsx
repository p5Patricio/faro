import { useId, useRef, useState, type FormEvent } from 'react';

type FileOutcome = { name: string; kind: 'created' | 'exists' } | { name: string; kind: 'error'; detail: string };

interface XmlImportFormProps {
  /** Visible label of the file input. */
  label: string;
  /** Sends one file's text; rejects with an `Error` whose message is shown to the user. */
  upload: (xml: string, filename: string) => Promise<{ created: boolean }>;
  /** Called once after every selected file was processed (even if some failed). */
  onDone: () => void;
}

const OUTCOME_TEXT = { created: 'Importada', exists: 'Ya existía' } as const;

/**
 * Multi-file XML import. Files are read in the browser with `File.text()` and
 * sent one at a time, so a bad file never blocks the others and each one gets
 * its own result line (announced politely to assistive technology).
 */
export function XmlImportForm({ label, upload, onDone }: XmlImportFormProps) {
  const inputId = useId();
  const hintId = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [outcomes, setOutcomes] = useState<FileOutcome[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const files = Array.from(fileInput.current?.files ?? []);
    if (files.length === 0) {
      setOutcomes([]);
      setNotice('Elige al menos un archivo XML.');
      return;
    }
    setBusy(true);
    setNotice(null);
    setOutcomes([]);
    for (const file of files) {
      let outcome: FileOutcome;
      try {
        const { created } = await upload(await file.text(), file.name);
        outcome = { name: file.name, kind: created ? 'created' : 'exists' };
      } catch (caught) {
        outcome = {
          name: file.name,
          kind: 'error',
          detail: caught instanceof Error ? caught.message : 'No se pudo importar el archivo.',
        };
      }
      setOutcomes((current) => [...current, outcome]);
    }
    if (fileInput.current) fileInput.current.value = '';
    setBusy(false);
    onDone();
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <label htmlFor={inputId} className="block text-xs font-medium text-ink-muted">{label}</label>
        <input
          ref={fileInput}
          id={inputId}
          name="xml"
          type="file"
          accept=".xml"
          multiple
          aria-describedby={hintId}
          className="mt-1.5 block w-full text-sm text-ink-secondary file:mr-3 file:h-11 file:cursor-pointer file:rounded-lg file:border file:border-cobalt/30 file:bg-cobalt/10 file:px-4 file:text-sm file:font-medium file:text-cobalt"
        />
        <p id={hintId} className="mt-1 text-xs text-ink-muted">
          Puedes elegir varios archivos .xml. Se leen en tu navegador y solo se envían a tu Faro local.
        </p>
      </div>
      <button
        type="submit"
        disabled={busy}
        className="inline-flex h-11 items-center justify-center rounded-lg border border-cobalt/30 bg-cobalt/10 px-4 text-sm font-medium text-cobalt transition hover:bg-cobalt/15 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? 'Importando' : 'Importar archivos'}
      </button>
      <div role="status" aria-live="polite">
        {notice ? <p className="text-sm text-status-critical">{notice}</p> : null}
        {outcomes.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {outcomes.map((outcome, index) => (
              <li key={`${outcome.name}-${index}`} className={outcome.kind === 'error' ? 'text-status-critical' : 'text-ink-secondary'}>
                <span className="font-medium text-ink">{outcome.name}</span>
                {': '}
                {outcome.kind === 'error' ? `Error: ${outcome.detail}` : OUTCOME_TEXT[outcome.kind]}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </form>
  );
}
