import { OperatorShell } from "../src/components/operator/operator-shell";
import { ErrorBoundary } from "../src/components/error-boundary";

export default function Page() {
  return (
    <ErrorBoundary>
      <OperatorShell />
    </ErrorBoundary>
  );
}