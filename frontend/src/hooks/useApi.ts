"use client";

import { useState, useCallback } from "react";

interface ApiState<T> {
  isLoading: boolean;
  error: string | null;
  data: T | null;
}

export function useApi<T>(
  apiCall: () => Promise<T>
): [ApiState<T>, () => Promise<T | null>] {
  const [state, setState] = useState<ApiState<T>>({
    isLoading: false,
    error: null,
    data: null,
  });

  const execute = useCallback(async (): Promise<T | null> => {
    setState({ isLoading: true, error: null, data: null });
    try {
      const result = await apiCall();
      setState({ isLoading: false, error: null, data: result });
      return result;
    } catch (err) {
      const error = err instanceof Error ? err.message : "Unknown error";
      setState({ isLoading: false, error, data: null });
      return null;
    }
  }, [apiCall]);

  return [state, execute];
}
