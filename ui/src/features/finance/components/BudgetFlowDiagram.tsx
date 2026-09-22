import { DEFAULT_CURRENCY, formatCents } from '../lib/format.ts';
import type { MonthlyBucketSummary, MonthlySummary } from '../types.ts';

interface BudgetFlowDiagramProps {
  buckets: MonthlySummary['buckets'];
  incomeCents: number;
  dataSufficient: boolean;
}

/**
 * Fixed 50/30/20 geometry, ported 1:1 from the approved mockup's SVG
 * (viewBox 0 0 640 190). The three ribbon/bar widths are ALWAYS these
 * proportions -- that is the rule itself, not something computed from
 * data -- so only the text labels change per month, never the shape.
 */
const INCOME_BAR = { x: 20, width: 600 };
// Bottom (bucket) bars carry an 8-unit gap between each pair, matching the
// dataviz mark-spec's "surface gap between fills" rule; the top (income) bar
// has NO internal gaps -- income is one continuous whole. Widths below are
// exactly 50/30/20 of the 600-unit bar minus the two 8-unit gaps (584
// remaining -> 292/175/117), so ribbon and bar edges always meet exactly --
// see the ribbon paths below, which share these same x values.
const NECESIDAD = { x: 20, width: 292, label: 'Necesidad' };
const DESEO = { x: 320, width: 175, label: 'Deseo' };
const AHORRO = { x: 503, width: 117, label: 'Ahorro' };

/**
 * Data-driven 50/30/20 flow diagram: income flows down into the three
 * fixed-width buckets. Handles `data_sufficient: false` / zero income by
 * still drawing the full shape (no NaN, no division), just swapping the
 * figures for an honest "sin datos" caption.
 */
export function BudgetFlowDiagram({ buckets, incomeCents, dataSufficient }: BudgetFlowDiagramProps) {
  const hasData = dataSufficient && incomeCents > 0;

  return (
    <div className="rounded-2xl border border-hairline bg-surface px-5 pb-2 pt-5">
      <h2 className="text-[13px] font-semibold tracking-wide text-ink-secondary">Reparto 50/30/20</h2>
      <p className="mb-1.5 text-xs text-ink-muted">
        {hasData ? 'De cada peso que entra, así se está yendo este mes.' : 'Sin datos este mes.'}
      </p>
      <svg
        viewBox="0 0 640 190"
        className="w-full"
        role="img"
        aria-label="Diagrama de flujo del ingreso hacia Necesidad, Deseo y Ahorro e inversión"
      >
        <rect x={INCOME_BAR.x} y={14} width={INCOME_BAR.width} height={14} rx={4} fill="var(--color-cobalt)" />
        <text x={INCOME_BAR.x} y={10} fill="var(--color-ink-secondary)" fontWeight={600} fontSize={12}>
          {hasData ? `Ingreso · ${formatCents(incomeCents, DEFAULT_CURRENCY)}` : 'Ingreso · sin datos'}
        </text>

        {/*
          Each ribbon's top edge is a slice of the CONTINUOUS income bar
          (20-320-500-620, no internal gaps); its bottom edge matches its own
          bucket bar exactly (NECESIDAD/DESEO/AHORRO above), which does carry
          the 8-unit gaps. Only the edge shared with a neighboring top slice
          is a straight vertical line (both endpoints share one x, so the
          path closes cleanly with no seam); the edge that must narrow or
          widen toward its own gapped bar is the one curve per ribbon. This
          is the fix for a real rendering bug in the first version of this
          diagram: ribbon 2 previously bottomed out at x=348 while its own
          bucket bar started at x=328, leaving an unfilled 20-unit notch
          between them.
        */}
        <path
          d="M20,28 L320,28 C320,80 312,80 312,120 L20,120 Z"
          fill="var(--color-cat-vivienda)"
          fillOpacity={0.5}
        />
        <path
          d="M320,28 L500,28 C500,80 495,80 495,120 L320,120 Z"
          fill="var(--color-cat-personales)"
          fillOpacity={0.5}
        />
        <path
          d="M500,28 L620,28 L620,120 L503,120 C503,80 500,80 500,28 Z"
          fill="var(--color-cat-ahorro)"
          fillOpacity={0.5}
        />

        <rect x={NECESIDAD.x} y={120} width={NECESIDAD.width} height={14} rx={4} fill="var(--color-cat-vivienda)" />
        <rect x={DESEO.x} y={120} width={DESEO.width} height={14} rx={4} fill="var(--color-cat-personales)" />
        <rect x={AHORRO.x} y={120} width={AHORRO.width} height={14} rx={4} fill="var(--color-cat-ahorro)" />

        <BucketLabels x={NECESIDAD.x} label={NECESIDAD.label} bucket={buckets.necesidad} hasData={hasData} />
        <BucketLabels x={DESEO.x} label={DESEO.label} bucket={buckets.deseo} hasData={hasData} />
        <BucketLabels x={AHORRO.x} label={AHORRO.label} bucket={buckets.ahorro_inversion} hasData={hasData} />
      </svg>
    </div>
  );
}

function BucketLabels({
  x,
  label,
  bucket,
  hasData,
}: {
  x: number;
  label: string;
  bucket: MonthlyBucketSummary;
  hasData: boolean;
}) {
  return (
    <>
      <text x={x} y={150} fill="var(--color-ink)" fontWeight={600} fontSize={13}>
        {label}
      </text>
      <text x={x} y={167} fill="var(--color-ink-muted)" fontSize={11}>
        {hasData
          ? `${formatCents(bucket.actual_cents, DEFAULT_CURRENCY)} de ${formatCents(bucket.target_cents, DEFAULT_CURRENCY)} objetivo`
          : 'sin datos este mes'}
      </text>
    </>
  );
}
