import { useId, type ComponentProps, type ReactNode } from 'react';

type ButtonProps = ComponentProps<'button'> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' };
export function Button({ variant = 'secondary', className = '', type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={`ui-button ui-button--${variant} ${className}`} {...props} />;
}
export function IconButton({ label, children, ...props }: Omit<ButtonProps, 'aria-label'> & { label: string; children: ReactNode }) {
  return <Button {...props} aria-label={label} className={`ui-icon-button ${props.className ?? ''}`}>{children}</Button>;
}
// Keep native controls and their complete HTML API, including ref, validation and aria-describedby.
export function Input({ className = '', ...props }: ComponentProps<'input'>) {
  return <input className={`ui-control ${className}`} {...props} />;
}
export function Textarea({ className = '', ...props }: ComponentProps<'textarea'>) {
  return <textarea className={`ui-control ${className}`} {...props} />;
}
export function Select({ className = '', ...props }: ComponentProps<'select'>) {
  return <select className={`ui-control ${className}`} {...props} />;
}
export function Checkbox({ label, id: suppliedId, className = '', ...props }: Omit<ComponentProps<'input'>, 'type'> & { label: ReactNode }) {
  const generatedId = useId();
  const id = suppliedId ?? generatedId;
  return <label className={`ui-checkbox ${className}`} htmlFor={id}><input {...props} id={id} type="checkbox" /><span>{label}</span></label>;
}
