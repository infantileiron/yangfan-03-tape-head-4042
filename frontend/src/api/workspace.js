import { request } from './client.js';

export const api = {
  signIn: data => request('/auth/login', { method: 'POST', body: data }),
  profile: () => request('/profile'),
  datasets: () => request('/datasets'),
  dataset: id => request('/datasets/' + id),
  upload: data => request('/datasets', { method: 'POST', body: data }),
  runs: () => request('/runs'),
  run: id => request('/runs/' + id),
  submit: data => request('/runs', { method: 'POST', body: data }),
  review: (id, data) => request('/runs/' + id + '/review', { method: 'POST', body: data }),
  reviews: () => request('/reviews'),
  audit: () => request('/audit'),
  reels: () => request('/reels'),
  revokeReel: (reel, data = {}) => request('/reels/' + encodeURIComponent(reel) + '/revoke', { method: 'POST', body: data }),
  baselines: (params = '') => request('/baselines' + params),
  baselinePlan: datasetId => request('/baselines/plan?dataset_id=' + encodeURIComponent(datasetId)),
  recompute: data => request('/baselines/recompute', { method: 'POST', body: data }),
  download: path => request(path, { download: true }),
};
