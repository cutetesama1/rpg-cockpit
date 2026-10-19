const PATHS = {
  book: "M4 4h6a3 3 0 0 1 2 1 3 3 0 0 1 2-1h6v15h-6a3 3 0 0 0-2 1 3 3 0 0 0-2-1H4z M12 5v15 M7 8h2 M15 8h2 M7 11h2 M15 11h2",
  library: "M4 4v16 M8 4v16 M13 5v15 M16 4l4 15 M3 20h18",
  spark: "M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
  save: "M5 3h12l4 4v14H3V3z M7 3v6h9V3 M7 21v-7h10v7",
  settings: "M9 4l1-2h4l1 2 2 1 2-.2 2 3-1 2v4l1 2-2 3-2-.2-2 1-1 2h-4l-1-2-2-1-2 .2-2-3 1-2v-4L3 8l2-3 2 .2z M15.5 12a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0",
  flask: "M9 3h6 M10 3v6L4 19a1.5 1.5 0 0 0 1.3 2h13.4a1.5 1.5 0 0 0 1.3-2L14 9V3 M7.5 14h9",
  help: "M9 8a3 3 0 1 1 5 2.2c-1.3.7-2 1.2-2 2.8 M12 17h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  undo: "M8 5L3 10l5 5 M3 10h11a6 6 0 0 1 0 12",
  reset: "M20 7v5h-5 M20 12a8 8 0 1 0-2 5",
};
export default function UiIcon({ name }: { name: keyof typeof PATHS }) {
  return <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={PATHS[name]} /></svg>;
}
