export function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) {
    return false;
  }

  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
    return true;
  }

  if ((target as HTMLElement).isContentEditable) {
    return true;
  }

  const editableAncestor = target.closest("input, textarea, select, [contenteditable='true'], [contenteditable='']");
  return Boolean(editableAncestor);
}
