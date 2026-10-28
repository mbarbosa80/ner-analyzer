import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export interface JobState {
  id: string;
  kind: string;
  state: "pending" | "running" | "done" | "error" | "cancelled";
  progress: number;
  stage: string;
  result: any;
  error: string;
  running: boolean;
}

/**
 * Starts a background operation and polls it until it finishes.
 *
 * Polling rather than a socket is deliberate: this is a single-user desktop tool
 * on localhost, one request every 600 ms costs nothing, and it keeps working if
 * the server restarts mid-job — the job row survives and the next poll picks it
 * up. `cancel` is the reason the whole thing exists; before it, the only way to
 * stop a runaway analysis was to kill the process.
 */
export function useJob() {
  const [job, setJob] = useState<JobState | null>(null);
  const timer = useRef<number | null>(null);

  const stopPolling = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };

  useEffect(() => stopPolling, []);

  const poll = useCallback((jobId: string, onDone?: (j: JobState) => void) => {
    const tick = async () => {
      try {
        const j = (await api.job(jobId)) as JobState;
        setJob(j);
        if (j.running) {
          timer.current = window.setTimeout(tick, 600);
        } else {
          stopPolling();
          onDone?.(j);
        }
      } catch {
        stopPolling();
      }
    };
    void tick();
  }, []);

  /**
   * `start` takes the API call that kicks the job off. If the endpoint answered
   * synchronously (no job id) the result is handed straight to `onDone`, so the
   * same call site works either way.
   */
  const start = useCallback(
    async (fn: () => Promise<any>, onDone?: (j: JobState) => void) => {
      stopPolling();
      setJob(null);
      const started = await fn();
      if (started?.job_id) {
        setJob({
          id: started.job_id, kind: "", state: "pending", progress: 0,
          stage: "queued", result: null, error: "", running: true,
        });
        poll(started.job_id, onDone);
        return null;
      }
      onDone?.({
        id: "", kind: "", state: "done", progress: 1, stage: "finished",
        result: started, error: "", running: false,
      });
      return started;
    },
    [poll],
  );

  /**
   * Like `start`, but the promise settles when the job has finished (4.6.0):
   * several books chosen together are read one after the other, each to its
   * end, so the second copy of the same book is refused instead of racing
   * the first.
   */
  const startAndWait = useCallback(
    (fn: () => Promise<any>): Promise<JobState> =>
      new Promise<JobState>((resolve, reject) => {
        start(fn, (j) => resolve(j)).catch(reject);
      }),
    [start],
  );

  const cancel = useCallback(async () => {
    if (!job?.id) return;
    await api.cancelJob(job.id);
  }, [job?.id]);

  const clear = useCallback(() => {
    stopPolling();
    setJob(null);
  }, []);

  return { job, start, startAndWait, cancel, clear, busy: !!job?.running };
}
