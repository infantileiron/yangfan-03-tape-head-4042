export const roles = { analyst: '分析员', reviewer: '复核员', viewer: '观察员' };
export const stages = { queued: '排队中', running: '计算中', succeeded: '已完成', failed: '失败' };
export const decisions = { approve: '签发', hold: '暂缓' };
export const baselineStatus = {
  active: '基线有效',
  invalid: '已失效',
  suspended: '该档暂停',
  stale: '旧计算作废',
};
export const reelStatus = { qualified: '合格', revoked: '已撤销' };
export const auditActions = {
  dataset_imported: '导入数据',
  run_queued: '提交计算',
  run_succeeded: '完成计算',
  run_failed: '计算失败',
  review_approve: '签发交接',
  review_hold: '暂缓交接',
  reel_revoked: '撤销合格卷',
  baseline_invalidated: '基线失效',
  baselines_recomputed: '重算基线',
};
