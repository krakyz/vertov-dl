import type { Job } from './model';

/** Only jobs explicitly started in this page may trigger a browser download. */
export class AutoDownload {
  private pending = new Set<string>();
  watch(id: string) { this.pending.add(id); }
  forget(id: string) { this.pending.delete(id); }
  snapshot() { return [...this.pending]; }
  clear() { this.pending.clear(); }
  update(jobs: Iterable<Job>, start: (job: Job) => void) {
    for (const job of jobs) {
      if (!this.pending.has(job.id) || job.kind !== 'download') continue;
      if (['failed', 'cancelled', 'expired'].includes(job.state)) this.pending.delete(job.id);
      if (job.state !== 'completed') continue;
      // Remove before dispatch: repeated SSE snapshots must not download twice.
      this.pending.delete(job.id);
      start(job);
    }
  }
}
