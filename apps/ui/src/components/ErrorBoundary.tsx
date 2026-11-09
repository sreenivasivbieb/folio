/** Keeps one broken view from blanking the whole window: shows the error with a retry. */
import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; resetKey?: unknown };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="empty-state" style={{ height: "100%" }}>
        <h3>This view hit a problem</h3>
        <p className="small">{this.state.error.message}</p>
        <div className="actions">
          <button type="button" className="btn primary" onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      </div>
    );
  }
}
