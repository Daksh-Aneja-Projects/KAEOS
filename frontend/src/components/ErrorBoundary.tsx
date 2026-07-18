import React, { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Catches render errors in any child component tree and shows a recovery UI
 * instead of crashing the entire application.
 */
export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[KAEOS ErrorBoundary]', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          height: '100%', minHeight: 200, padding: 32, gap: 16, fontFamily: '"Inter", sans-serif',
        }}>
          <div style={{
            width: 48, height: 48, borderRadius: 12,
            background: 'rgba(229, 83, 75, 0.12)', display: 'flex',
            alignItems: 'center', justifyContent: 'center', fontSize: 24,
          }}>⚠</div>
          <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0, color: '#f7f8f8' }}>
            {this.props.fallbackTitle || 'Module Error'}
          </h3>
          <p style={{ fontSize: 13, color: '#8a8f98', margin: 0, maxWidth: 400, textAlign: 'center' }}>
            {this.state.error?.message || 'An unexpected error occurred in this module.'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              padding: '8px 16px', borderRadius: 8, fontSize: 13, fontWeight: 500,
              background: '#5e6ad2', color: '#fff', border: 'none', cursor: 'pointer',
              marginTop: 8, transition: 'background 0.2s',
            }}
            onMouseOver={e => (e.currentTarget.style.background = '#828fff')}
            onMouseOut={e => (e.currentTarget.style.background = '#5e6ad2')}
          >
            Retry Module
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
