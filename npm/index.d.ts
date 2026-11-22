/** Something that needs attention in Power BI: a blocking dialog, a banner, or a broken visual. */
export interface Alerts {
  blocked?: boolean;
  windows?: Array<{ title: string; kind: 'native' | 'legacy-ie' | 'webview2'; text: string; buttons: string[] }>;
  dialogs?: Array<{ view: string; text: string; buttons: string[] }>;
  banners?: Array<{ view: string; text: string }>;
  visual_errors?: Array<{ index: number; type: string; label: string; error_text: string }>;
}

/** The JSON object every pbidriver command prints. Fields beyond these depend on the command. */
export interface Result {
  ok: boolean;
  error?: string;
  alerts?: Alerts;
  [key: string]: unknown;
}

export interface RunOptions {
  cwd?: string;
  env?: Record<string, string | undefined>;
  /** Milliseconds before the command is stopped. */
  timeout?: number;
}

/** How the Python CLI is started: uvx, a Python interpreter, or PBIDRIVER_PYTHON. */
export interface Runner {
  command: string;
  prefix: string[];
  via: string;
}

/** Run one command, e.g. run(['shot', '--page', 'Overview']). Resolves with its JSON result. */
export function run(args: Array<string | number>, options?: RunOptions): Promise<Result>;

export function resolveRunner(options?: { install?: boolean; log?: (message: string) => void }): Runner;

/** The package version; the matching Python package version is used. */
export const version: string;
