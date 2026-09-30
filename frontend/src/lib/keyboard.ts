/** Keys typed into a field, held down, or with a modifier are not shortcuts. */
export function isShortcut(event: KeyboardEvent): boolean {
  const target = event.target as HTMLElement | null;
  const typing = target?.closest("input, textarea, select, [contenteditable=true]");
  return (
    !typing &&
    !event.repeat &&
    !event.isComposing &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey
  );
}
