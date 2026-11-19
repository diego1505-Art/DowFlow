import { useCallback, useContext } from "react";
import { UNSAFE_NavigationContext } from "react-router-dom";

export function useStableNavigate(): (to: string, state?: unknown) => void {
  const { navigator } = useContext(UNSAFE_NavigationContext);
  return useCallback(
    (to: string, state?: unknown) => navigator.push(to, state),
    [navigator],
  );
}
