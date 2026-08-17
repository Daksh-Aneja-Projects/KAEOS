import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import Field from './Field';

describe('Field', () => {
  it('wires the label to the control so it is reachable by accessible name', () => {
    const { getByLabelText } = render(
      <Field label="Company name" hint="Auto-derived">
        <input defaultValue="Acme" />
      </Field>,
    );
    // Fails if htmlFor/id association is dropped: getByLabelText only matches a
    // control that is actually associated with its <label>.
    const control = getByLabelText('Company name') as HTMLInputElement;
    expect(control.value).toBe('Acme');
  });

  it('reuses the child\'s own id when it already has one', () => {
    const { getByLabelText } = render(
      <Field label="Tenant ID">
        <input id="fixed-id" defaultValue="tenant_acme" />
      </Field>,
    );
    const control = getByLabelText('Tenant ID') as HTMLInputElement;
    expect(control.id).toBe('fixed-id');
    expect(control.value).toBe('tenant_acme');
  });
});
