// While something is waiting for raw key input (e.g. a shortcut recorder),
// Escape must cancel that input instead of closing the dialog behind it.
// Dialogs register their Escape listener on window before the recorder does,
// so they would otherwise win; they check this guard and stand down.
let activeGuards = 0;

export function acquireEscapeGuard(): () => void {
  activeGuards += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    activeGuards = Math.max(0, activeGuards - 1);
  };
}

export function isEscapeGuarded(): boolean {
  return activeGuards > 0;
}
