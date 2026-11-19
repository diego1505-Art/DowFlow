// One place that decides "the app is going away".
//
// Quitting used to depend on a chain of events (main window closed -> overlay
// destroyed -> app.quit() -> window-all-closed). If any link threw or stalled,
// the hidden overlay window or a child process kept the process alive with the
// single-instance lock still held, so the next launch exited silently and no
// window ever appeared. This helper makes the sequence idempotent, isolates
// failures between cleanup steps and force-exits if a graceful quit hangs.

export interface ShutdownDeps {
  /** release everything the process owns; each step runs even if another throws */
  cleanup: Array<() => void>;
  /** graceful quit (app.quit) */
  quit: () => void;
  /** hard exit (app.exit) used when the graceful quit does not finish in time */
  forceExit: () => void;
  /** how long the graceful quit may take before we force the exit */
  watchdogMs: number;
}

export interface Shutdown {
  /** true once a quit has been requested; later launches should not rely on this process */
  isQuitting(): boolean;
  /** mark quitting, release resources and arm the watchdog; safe to call repeatedly */
  begin(): void;
  /** begin() and ask the app to quit */
  quit(): void;
}

export function createShutdown(deps: ShutdownDeps): Shutdown {
  let started = false;

  const begin = () => {
    if (started) return;
    started = true;
    for (const step of deps.cleanup) {
      try {
        step();
      } catch (err) {
        console.error("[shutdown] cleanup step failed:", err);
      }
    }
    setTimeout(() => {
      console.warn("[shutdown] graceful quit did not finish, forcing exit");
      deps.forceExit();
    }, deps.watchdogMs);
  };

  return {
    isQuitting: () => started,
    begin,
    quit() {
      begin();
      try {
        deps.quit();
      } catch (err) {
        console.error("[shutdown] quit failed, forcing exit:", err);
        deps.forceExit();
      }
    },
  };
}
