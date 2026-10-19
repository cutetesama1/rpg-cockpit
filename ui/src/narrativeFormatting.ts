/** Isolate complete quoted dialogue for display; never rewrite the saved narrative. */
export function formatNarrativeDialogue(narrative: string): string {
  const text = narrative.replace(/\r\n?/g, "\n");
  const pairs: Record<string, string> = { "“": "”", "「": "」", "『": "』", '"': '"' };
  const stack: string[] = [];
  const ranges: { start: number; end: number }[] = [];
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"') {
      let slashes = 0;
      for (let j = i - 1; j >= 0 && text[j] === "\\"; j -= 1) slashes += 1;
      if (slashes % 2) continue;
    }
    if (stack.length && char === stack[stack.length - 1]) {
      stack.pop();
      if (!stack.length) {
        let end = i + 1;
        // Keep punctuation after a closing quote on the same line.
        while (end < text.length && /[，。！？；：、,.!?;:…]/.test(text[end])) end += 1;
        ranges.push({ start, end });
        i = end - 1;
      }
    } else if (pairs[char]) {
      if (!stack.length) start = i;
      stack.push(pairs[char]);
    }
  }
  let result = "";
  let cursor = 0;
  for (const range of ranges) {
    const before = text.slice(cursor, range.start).replace(/[ \t]+$/, "");
    result += before;
    if (result && !result.endsWith("\n")) result += "\n";
    result += text.slice(range.start, range.end);
    cursor = range.end;
    while (text[cursor] === " " || text[cursor] === "\t") cursor += 1;
    if (cursor < text.length && text[cursor] !== "\n") result += "\n";
  }
  return result + text.slice(cursor);
}
