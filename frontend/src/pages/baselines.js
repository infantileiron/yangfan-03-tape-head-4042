import { api } from '../api/workspace.js';
import { heading } from '../components/common/heading.js';
import { baselineStatus, reelStatus } from '../constants/enums.js';
import { notice } from '../hooks/forms.js';
import { escapeHtml as e, timeText } from '../utils/format.js';

function badge(value, labels) {
  return `<span class="status s-${e(value)}">${e(labels[value] ?? value)}</span>`;
}

export async function baselinesPage(profile, account) {
  const [reels, baselines, datasets] = await Promise.all([
    api.reels(), api.baselines(), api.datasets(),
  ]);
  const staff = account.role === 'analyst' || account.role === 'reviewer';

  const reelRows = reels.map(reel => `
    <tr>
      <td><strong>${e(reel.reel)}</strong></td>
      <td>${(reel.tiers || (reel.tier ? [reel.tier] : [])).map(t => e(t) + ' cm/s').join('、') || '—'}</td>
      <td>${(reel.cohorts || []).map(c => e(c)).join('、') || '—'}</td>
      <td>${badge(reel.status, reelStatus)}</td>
      <td class="muted">${e(reel.reason || '')}</td>
      <td>${reel.status === 'qualified' && staff
        ? `<button type="button" class="quiet revoke-reel" data-reel="${e(reel.reel)}">撤销</button>`
        : (reel.revoked_at ? `<span class="muted">${e(timeText(reel.revoked_at))}</span>` : '')}</td>
    </tr>`).join('');

  const baselineRows = baselines.map(b => `
    <tr>
      <td>${e(b.tier)} cm/s</td>
      <td>${badge(b.status, baselineStatus)}${b.is_current ? ' <span class="muted">当前</span>' : ''}</td>
      <td>${(b.fit_reels || []).length} 卷 / ${(b.holdout_reels || []).length} 卷</td>
      <td title="${e((b.used_reels || []).join('、'))}">${(b.used_reels || []).slice(0, 4).map(e).join('、')}${(b.used_reels || []).length > 4 ? ' …' : ''}</td>
      <td>${b.threshold != null ? Number(b.threshold).toFixed(3) : '—'}</td>
      <td>${b.run_id ? `<a href="#results/${b.run_id}">计算单</a>` : '—'}</td>
      <td class="muted">${e(timeText(b.created_at))}</td>
    </tr>
    ${b.note ? `<tr class="note-row"><td colspan="7" class="muted">${e(b.note)}</td></tr>` : ''}`).join('');

  const recomputeForm = staff && datasets.length ? `
    <form id="recompute-form" class="inline-form">
      <label>数据版本
        <select name="dataset_id">${datasets.map(d => `<option value="${d.id}">${e(d.name)} · ${d.count} 行</option>`).join('')}</select>
      </label>
      <label>分位<input type="number" name="parameter" min="0.8" max="0.99" step="0.01" value="0.95"></label>
      <button type="submit">重算各档基线</button>
      <div class="form-error" data-error role="alert"></div>
    </form>` : '<p class="muted">分析员或复核员可在此重算基线。</p>';

  return {
    html: heading('合格卷与基线', '撤销合格卷会立即失效用过它拟合或定门槛的基线；重算时同卷不得兼作拟合与留出，留出不足三卷暂停该档。') +
      `<section class="work">
        <div class="work-head"><h2>重算</h2><button type="button" class="quiet" id="refresh-baselines">刷新</button></div>
        ${recomputeForm}
        <p class="muted">规则：同一卷不能既参与拟合又当留出；每档至少需要 3 卷不同的留出合格卷。并发重算时，使用过撤销卷的旧计算即使晚完成也不能签发；该档重算出干净的新基线后恢复签发。已签发的复录交班单始终保留签发时的快照，可继续导出。</p>
      </section>
      <div class="board">
        <aside class="side"><h2>合格卷（${reels.length}）</h2>
          <div class="table-scroll"><table><thead><tr><th>卷号</th><th>带速</th><th>用途</th><th>状态</th><th>原因</th><th></th></tr></thead>
          <tbody>${reelRows || '<tr><td colspan="6" class="muted">暂无卷记录</td></tr>'}</tbody></table></div>
        </aside>
        <section class="work"><h2>各档基线（${baselines.length}）</h2>
          <div class="table-scroll"><table><thead><tr><th>档</th><th>状态</th><th>拟合/留出</th><th>用到的卷</th><th>门槛</th><th>计算单</th><th>时间</th></tr></thead>
          <tbody>${baselineRows || '<tr><td colspan="7" class="muted">计算后在此登记基线。</td></tr>'}</tbody></table></div>
        </section>
      </div>`,
    mount(root, refresh) {
      root.querySelector('#refresh-baselines').onclick = refresh;
      root.querySelectorAll('.revoke-reel').forEach(button => {
        button.onclick = async () => {
          const reel = button.dataset.reel;
          button.disabled = true;
          try {
            const result = await api.revokeReel(reel, { reason: '合格卷撤销，源数据更新' });
            notice(`已撤销 ${reel}，${result.invalidated_baseline_ids?.length ?? 0} 条基线立即失效。`);
            refresh();
          } catch (error) {
            notice(error.message, 'error');
            button.disabled = false;
          }
        };
      });
      const form = root.querySelector('#recompute-form');
      if (form) {
        form.addEventListener('submit', async event => {
          event.preventDefault();
          const data = new FormData(form);
          const error = form.querySelector('[data-error]');
          const button = form.querySelector('button[type=submit]');
          error.textContent = '';
          button.disabled = true;
          try {
            const result = await api.recompute({
              dataset_id: data.get('dataset_id'),
              parameter: Number(data.get('parameter')),
            });
            const paused = result.baselines.filter(b => b.status === 'suspended').length;
            notice(`重算完成：${result.baselines.length} 档基线，${paused} 档暂停。`);
            refresh();
          } catch (problem) {
            error.textContent = problem.message;
          } finally {
            button.disabled = false;
          }
        });
      }
    },
  };
}
