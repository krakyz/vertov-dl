import type { Job } from './model';

export class CardProgress {
  private id = '';
  private percent = 0;
  update(job?: Job, error = false) {
    if (job?.id !== this.id) { this.id = job?.id || ''; this.percent = 0; }
    const data = job?.progress;
    if (job?.state === 'completed') this.percent = 100;
    else if (data?.total && (!['failed', 'cancelled', 'expired'].includes(job!.state) || this.percent === 0)) {
      this.percent = Math.max(0, Math.min(100, data.downloaded / data.total * 100));
    }
    return { percent: this.percent, tone: error || job?.state === 'failed' ? 'error'
      : job && ['downloading', 'processing', 'completed', 'queued', 'probing'].includes(job.state) ? 'success' : 'neutral' };
  }
}
