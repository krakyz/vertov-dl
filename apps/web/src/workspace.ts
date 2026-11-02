export const WORKSPACE_KEY = 'vertovdl-workspace-v1';
export type Workspace = {
  version: 1; values: string[]; savedBatch: string[]; batch: boolean; advanced: boolean;
  quality: string; entries: {url: string; probeId?: string; downloadId?: string}[];
  pendingDownloads: string[];
};
const validId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
export function readWorkspace(raw: string | null): Workspace | undefined {
  if (!raw || raw.length > 256000) return;
  try {
    const data = JSON.parse(raw);
    if (data.version !== 1 || !Array.isArray(data.values) || !Array.isArray(data.entries)) return;
    const strings = (items: unknown) => Array.isArray(items) ? items.filter((v): v is string => typeof v === 'string' && v.length <= 4096).slice(0, 21) : [];
    const values = strings(data.values);
    if (values.filter(value => value.trim()).length > 20) return;
    return {
      version: 1, values: values.length ? values : [''], savedBatch: strings(data.savedBatch),
      batch: data.batch === true, advanced: data.advanced === true,
      quality: ['best', '1080', '720', '360'].includes(data.quality) ? data.quality : 'best',
      entries: data.entries.slice(0, 1000).filter((item: any) => item && typeof item.url === 'string' && item.url.length <= 4096)
        .map((item: any) => ({url:item.url, probeId:validId(item.probeId) ? item.probeId : undefined, downloadId:validId(item.downloadId) ? item.downloadId : undefined})),
      pendingDownloads: Array.isArray(data.pendingDownloads) ? data.pendingDownloads.filter(validId).slice(0, 1000) : [],
    };
  } catch { return; }
}
