import { useId, cloneElement } from 'react';
import type { ReactElement, ReactNode, CSSProperties } from 'react';

/**
 * Labeled form row with a real `<label htmlFor>`/control association.
 *
 * Many forms render a visible `<label>` next to an `<input>` but never wire
 * them together, so assistive tech reads the control as unlabeled and clicking
 * the label does nothing. Field owns the id: it mints one with `useId()` (or
 * reuses the child's own `id` if it already has one) and binds the `<label>` to
 * it, so association is correct by construction.
 *
 * Style defaults match the existing form rows (12px label, 11px hint). Pass
 * `labelStyle`/`className` to match a specific view's palette.
 */
interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  className?: string;
  labelClassName?: string;
  labelStyle?: CSSProperties;
  hintClassName?: string;
  hintStyle?: CSSProperties;
  /** Exactly one control (input/select/textarea). Field injects its `id`. */
  children: ReactElement<{ id?: string }>;
}

export default function Field({
  label,
  hint,
  className,
  labelClassName = 'text-[12px] font-medium mb-1.5 block',
  labelStyle,
  hintClassName = 'text-[11px] mt-1',
  hintStyle,
  children,
}: FieldProps) {
  const generatedId = useId();
  const id = children.props.id ?? generatedId;
  return (
    <div className={className}>
      <label htmlFor={id} className={labelClassName} style={labelStyle}>{label}</label>
      {cloneElement(children, { id })}
      {hint != null && <p className={hintClassName} style={hintStyle}>{hint}</p>}
    </div>
  );
}
