/** Markdown evidence is generated from observed runner log entries, never intent. */
import type { RunState } from "./runner";

export const CAMERA_THUMBNAIL_WIDTH = 320;

/** Capture report evidence without touching the live MJPEG element itself. */
export function captureCameraThumbnail(
  image: HTMLImageElement | null,
  canvasFactory: () => HTMLCanvasElement = () => document.createElement("canvas"),
): string | undefined {
  if (!image || image.naturalWidth <= 0 || image.naturalHeight <= 0) return undefined;
  try {
    const canvas = canvasFactory();
    canvas.width = CAMERA_THUMBNAIL_WIDTH;
    canvas.height = Math.max(1, Math.round(CAMERA_THUMBNAIL_WIDTH * image.naturalHeight / image.naturalWidth));
    const context = canvas.getContext("2d");
    if (!context) return undefined;
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/webp", 0.7);
  } catch {
    return undefined;
  }
}

const seconds = (milliseconds: number) => `${(Math.max(0, milliseconds) / 1000).toFixed(2)} s`;
const escapeCell = (value: string) => value.replaceAll("|", "\\|").replaceAll("\n", " ");

export function markdownReport(state: RunState): string {
  const title = escapeCell(state.modelName || "Untitled model");
  const started = state.startedAt ?? 0;
  const finished = state.finishedAt ?? (state.log.at(-1)?.finishedAt ?? started);
  const lines = [
    `# Run report — ${title}`,
    "",
    `Style: **${state.style.toUpperCase()}**  `,
    `Outcome: **${state.phase.toUpperCase()}**  `,
    `Total time: **${seconds(finished - started)}**`,
    "",
    "| Step | Command | Result | Duration | Vision |",
    "| ---: | --- | --- | ---: | --- |",
  ];
  state.log.forEach((entry, index) => {
    lines.push(`| ${index + 1} | \`${escapeCell(entry.command)}\` | ${escapeCell(entry.result)} | ${seconds(entry.finishedAt - entry.startedAt)} | ${escapeCell(entry.verification ?? "—")} |`);
  });

  if (state.failure) lines.push("", `Failure: **${escapeCell(state.failure)}**`);
  if (state.mismatch) {
    lines.push("", "## Command mismatch", "", `program: \`${state.mismatch.program}\`  `,
      `rig: \`${state.mismatch.rig}\``);
  }
  const evidence = state.log.filter(entry => entry.thumbnail);
  if (evidence.length) {
    lines.push("", "## Camera evidence", "");
    for (const entry of evidence) {
      lines.push(`![Camera after step ${entry.index + 1}](${entry.thumbnail})`, "");
    }
  }
  return `${lines.join("\n").trimEnd()}\n`;
}

export function downloadMarkdown(state: RunState): void {
  const blob = new Blob([markdownReport(state)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${(state.modelName || "run").replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-report.md`;
  link.click();
  URL.revokeObjectURL(url);
}
