/* Shared report renderer - used by the user dashboard and by the admin dashboard.
   renderReport(rootElement, report) draws: cards, 2-hour chart, daily, weekly,
   per-prompt usage, models/projects and stored snapshots. */
(function () {
  'use strict';
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  };
  var fmt = function (n) {
    n = Number(n) || 0;
    return n >= 1e9 ? (n / 1e9).toFixed(2) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' :
           n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(Math.round(n));
  };
  var full = function (n) { return Number(n || 0).toLocaleString(); };
  var when = function (t) {
    return t ? new Date(t * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';
  };
  var ago = function (t) {
    if (!t) return 'never';
    var s = Math.max(0, Date.now() / 1000 - t);
    if (s < 90) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  };
  var WLABEL = {today: 'Today', last_4h: 'Last 4 hours', last_24h: 'Last 24 hours', last_7d: 'Last 7 days', lifetime: 'Lifetime'};
  var NM = {input: 'Input', output: 'Output', cache_write: 'Cache write', cache_read: 'Cache read'};
  var COL = {input: 'var(--in)', output: 'var(--out)', cache_write: 'var(--cw)', cache_read: 'var(--cr)'};

  function tot(x, cache) {
    return (x.input || 0) + (x.output || 0) + (cache ? (x.cache_write || 0) + (x.cache_read || 0) : 0);
  }
  function parts(cache) { return cache ? ['input', 'output', 'cache_write', 'cache_read'] : ['input', 'output']; }

  function barChart(items, cache, labelFn, tipFn, maxLabels) {
    var W = 1000, H = 260, L = 54, R = 8, T = 10, B = 30, pw = W - L - R, ph = H - T - B;
    var ps = parts(cache);
    var max = 1;
    items.forEach(function (x) { max = Math.max(max, tot(x, cache)); });
    var n = items.length;
    var any = items.some(function (x) { return tot(x, cache) > 0; });
    if (!n || !any) return '<div class="empty">No usage in this period.</div>';
    var bw = pw / n, g = '', f, y, i;
    [0, 0.5, 1].forEach(function (f) {
      y = T + ph - f * ph;
      g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '" stroke="var(--line)"/>' +
           '<text x="' + (L - 6) + '" y="' + (y + 4) + '" text-anchor="end">' + fmt(Math.round(max * f)) + '</text>';
    });
    var every = Math.max(1, Math.ceil(n / (maxLabels || 10)));
    items.forEach(function (x, i) {
      var yy = T + ph, bars = '';
      ps.forEach(function (k) {
        var h = (x[k] || 0) / max * ph;
        if (h > 0) {
          yy -= h;
          bars += '<rect x="' + (L + i * bw + 0.5) + '" y="' + yy + '" width="' + Math.max(1, bw - 1) + '" height="' + h + '" fill="' + COL[k] + '"/>';
        }
      });
      var tip = tipFn(x) + '\n' + ps.map(function (k) { return NM[k] + ': ' + full(x[k]); }).join('\n') + '\nTotal: ' + full(tot(x, cache));
      g += '<g><title>' + esc(tip) + '</title><rect x="' + (L + i * bw) + '" y="' + T + '" width="' + bw + '" height="' + ph + '" fill="transparent"/>' + bars + '</g>';
      if (i % every === 0) g += '<text x="' + (L + i * bw) + '" y="' + (H - 10) + '">' + esc(labelFn(x)) + '</text>';
    });
    var legend = '<div class="legend">' + ps.map(function (k) {
      return '<span><i style="background:' + COL[k] + '"></i>' + NM[k] + '</span>';
    }).join('') + '</div>';
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" role="img">' + g + '</svg>' + legend;
  }

  function dayLabel(iso) {
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString([], {day: 'numeric', month: 'short'});
  }

  function usageTable(rows, cache, firstTitle, labelFn, extraCols) {
    if (!rows.length) return '<div class="empty">No usage yet</div>';
    var max = 1;
    rows.forEach(function (r) { max = Math.max(max, tot(r, cache)); });
    return '<div class="scroll"><table><tr><th>' + firstTitle + '</th><th>Tokens</th><th>Input</th><th>Output</th>' +
      (cache ? '<th>Cache write</th><th>Cache read</th>' : '') + '<th>Prompts</th><th>Replies</th></tr>' +
      rows.map(function (r) {
        return '<tr><td>' + esc(labelFn(r)) + '<div class="bar"><b style="width:' + (tot(r, cache) / max * 100) + '%"></b></div></td>' +
          '<td title="' + full(tot(r, cache)) + '"><b>' + fmt(tot(r, cache)) + '</b></td><td>' + fmt(r.input) + '</td><td>' + fmt(r.output) + '</td>' +
          (cache ? '<td>' + fmt(r.cache_write) + '</td><td>' + fmt(r.cache_read) + '</td>' : '') +
          '<td>' + full(r.prompts) + '</td><td>' + full(r.messages) + '</td></tr>';
      }).join('') + '</table></div>';
  }

  function simpleTable(title, rows, cache) {
    if (!rows.length) return '<table><tr><th>' + title + '</th></tr><tr><td class="empty">No usage in this period</td></tr></table>';
    var max = 1;
    rows.forEach(function (r) { max = Math.max(max, tot(r, cache)); });
    return '<table><tr><th>' + title + '</th><th>Tokens</th><th>Input</th><th>Output</th><th>Replies</th></tr>' +
      rows.map(function (r) {
        return '<tr><td>' + esc(r.name) + '<div class="bar"><b style="width:' + (tot(r, cache) / max * 100) + '%"></b></div></td>' +
          '<td title="' + full(tot(r, cache)) + '">' + fmt(tot(r, cache)) + '</td><td>' + fmt(r.input) + '</td><td>' + fmt(r.output) + '</td><td>' + full(r.messages) + '</td></tr>';
      }).join('') + '</table>';
  }

  var TABS = [['overview', 'Overview'], ['daily', 'Daily'], ['weekly', 'Weekly'], ['prompts', 'Prompts'], ['breakdown', 'Models & projects'], ['snapshots', 'Snapshots']];

  function draw(root) {
    var st = root._ctd, rep = root._rep;
    if (!rep) { root.innerHTML = '<div class="empty">No data yet.</div>'; return; }
    var c = st.cache, w = rep.windows || {};
    var html = '<div class="cards">' + Object.keys(WLABEL).map(function (k) {
      var x = w[k] || {};
      return '<div class="card"><div class="lbl">' + WLABEL[k] + '</div><div class="big" title="' + full(tot(x, c)) + '">' + fmt(tot(x, c)) + '</div>' +
        '<div class="sub">in ' + fmt(x.input) + ' · out ' + fmt(x.output) + '</div>' +
        '<div class="sub">cache write ' + fmt(x.cache_write) + ' · read ' + fmt(x.cache_read) + '</div>' +
        '<div class="sub">' + full(x.messages) + ' replies</div></div>';
    }).join('') + '</div>';

    html += '<div class="toolbar"><div class="tabs" style="margin:0;flex:1">' + TABS.map(function (t) {
      return '<button class="tab' + (st.tab === t[0] ? ' on' : '') + '" data-act="tab" data-v="' + t[0] + '">' + t[1] + '</button>';
    }).join('') + '</div><label class="chk"><input type="checkbox" data-act="cache"' + (c ? ' checked' : '') +
      '> include cache tokens</label></div>';

    html += '<div class="panel">';
    if (st.tab === 'overview') {
      html += '<div class="toolbar"><h2 style="margin:0">Tokens per 2 hours</h2><select data-act="days">' +
        [[1, 'Today'], [3, 'Last 3 days'], [7, 'Last 7 days'], [14, 'Last 14 days']].map(function (o) {
          return '<option value="' + o[0] + '"' + (st.days === o[0] ? ' selected' : '') + '>' + o[1] + '</option>';
        }).join('') + '</select></div>';
      var since = Date.now() / 1000 - st.days * 86400;
      var b = (rep.buckets || []).filter(function (x) { return x.start >= since - 7200; });
      html += barChart(b, c, function (x) {
        var d = new Date(x.start * 1000);
        return st.days <= 3 ? d.toLocaleDateString([], {day: 'numeric', month: 'short'}) + ' ' + String(d.getHours()).padStart(2, '0') + 'h'
                            : d.toLocaleDateString([], {day: 'numeric', month: 'short'});
      }, function (x) {
        return new Date(x.start * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) + ' (2h)';
      }, 10);
      html += '<p class="note">Tokens = input + output' + (c ? ' + cache write + cache read' : '') + '. Counted from Claude Code logs on this PC.</p>';
    } else if (st.tab === 'daily') {
      var dl = (rep.daily || []).slice(-30);
      html += '<h2>Daily usage (last ' + dl.length + ' days)</h2>' +
        barChart(dl, c, function (x) { return dayLabel(x.date); }, function (x) { return x.date; }, 10) +
        '<div style="height:14px"></div>' +
        usageTable(dl.slice().reverse(), c, 'Date', function (r) { return r.date; });
    } else if (st.tab === 'weekly') {
      var wl = rep.weekly || [];
      html += '<h2>Weekly usage (Mon–Sun)</h2>' +
        barChart(wl, c, function (x) { return dayLabel(x.week_start); }, function (x) { return 'Week of ' + x.week_start; }, 12) +
        '<div style="height:14px"></div>' +
        usageTable(wl.slice().reverse(), c, 'Week starting', function (r) { return r.week_start; });
    } else if (st.tab === 'prompts') {
      html += '<div class="toolbar"><h2 style="margin:0">Tokens used per prompt</h2>' +
        '<input data-act="q" placeholder="Search prompt text…" value="' + esc(st.q) + '" style="min-width:220px">' +
        '<select data-act="sort"><option value="time"' + (st.sort === 'time' ? ' selected' : '') + '>Newest first</option>' +
        '<option value="tokens"' + (st.sort === 'tokens' ? ' selected' : '') + '>Most tokens first</option></select></div>' +
        '<div class="scroll pbody"></div>' +
        '<p class="note">A prompt = one message you typed, with everything Claude did to answer it (all replies, tool use, sub-agents). ' +
        'Latest ' + ((rep.prompts || []).length) + ' prompts shown.</p>';
    } else if (st.tab === 'breakdown') {
      var bd = (rep.breakdown || {})[st.bdw] || {models: [], projects: []};
      html += '<div class="toolbar"><h2 style="margin:0">Where the tokens went</h2><div class="seg">' +
        [['today', 'Today'], ['last_7d', '7 days'], ['lifetime', 'Lifetime']].map(function (o) {
          return '<button data-act="bdw" data-v="' + o[0] + '"' + (st.bdw === o[0] ? ' class="on"' : '') + '>' + o[1] + '</button>';
        }).join('') + '</div></div><div class="two"><div class="scroll">' + simpleTable('Model', bd.models, c) +
        '</div><div class="scroll">' + simpleTable('Project folder', bd.projects, c) + '</div></div>';
    } else if (st.tab === 'snapshots') {
      var sn = rep.snapshots || [], a = c ? 'all' : 'io';
      html += '<h2>Stored snapshots (one every ' + (rep.interval_hours || 2) + ' hours while the dashboard is running)</h2>';
      if (!sn.length) html += '<div class="empty">No snapshot yet</div>';
      else html += '<div class="scroll"><table><tr><th>Time</th><th>Today</th><th>Last 4h</th><th>Lifetime</th><th>Added since previous</th></tr>' +
        sn.map(function (r, i) {
          var p = sn[i + 1];
          var d = p ? Math.max(0, r['life_' + a] - p['life_' + a]) : null;
          return '<tr><td>' + esc(when(r.ts)) + '</td><td>' + fmt(r['today_' + a]) + '</td><td>' + fmt(r['h4_' + a]) +
            '</td><td>' + fmt(r['life_' + a]) + '</td><td>' + (d === null ? '—' : '+' + fmt(d)) + '</td></tr>';
        }).join('') + '</table></div>';
    }
    html += '</div>';
    root.innerHTML = html;
    if (st.tab === 'prompts') fillPrompts(root);
  }

  function fillPrompts(root) {
    var el = root.querySelector('.pbody');
    if (!el) return;
    var st = root._ctd, c = st.cache, q = (st.q || '').toLowerCase();
    var rows = (root._rep.prompts || []).filter(function (p) { return !q || String(p.text).toLowerCase().indexOf(q) >= 0; });
    if (st.sort === 'tokens') rows = rows.slice().sort(function (a, b) { return tot(b, c) - tot(a, c); });
    rows = rows.slice(0, 200);
    if (!rows.length) { el.innerHTML = '<div class="empty">No prompts found</div>'; return; }
    var max = 1;
    rows.forEach(function (r) { max = Math.max(max, tot(r, c)); });
    el.innerHTML = '<table><tr><th class="l">Prompt</th><th>Tokens</th><th>Input</th><th>Output</th>' +
      (c ? '<th>Cache write</th><th>Cache read</th>' : '') + '<th>Replies</th></tr>' +
      rows.map(function (r) {
        return '<tr><td class="ptxt">' + esc(r.text) + '<br><small>' + esc(when(r.ts)) + ' · ' + esc(r.project || '') + '</small>' +
          '<div class="bar"><b style="width:' + (tot(r, c) / max * 100) + '%"></b></div></td>' +
          '<td title="' + full(tot(r, c)) + '"><b>' + fmt(tot(r, c)) + '</b></td><td>' + fmt(r.input) + '</td><td>' + fmt(r.output) + '</td>' +
          (c ? '<td>' + fmt(r.cache_write) + '</td><td>' + fmt(r.cache_read) + '</td>' : '') + '<td>' + full(r.messages) + '</td></tr>';
      }).join('') + '</table>';
  }

  function bind(root) {
    root.addEventListener('click', function (e) {
      var b = e.target.closest('[data-act]');
      if (!b || b.tagName === 'INPUT' || b.tagName === 'SELECT') return;
      var st = root._ctd;
      if (b.dataset.act === 'tab') st.tab = b.dataset.v;
      else if (b.dataset.act === 'bdw') st.bdw = b.dataset.v;
      else return;
      draw(root);
    });
    root.addEventListener('change', function (e) {
      var t = e.target, st = root._ctd;
      if (t.dataset.act === 'days') st.days = +t.value;
      else if (t.dataset.act === 'cache') st.cache = t.checked;
      else if (t.dataset.act === 'sort') { st.sort = t.value; fillPrompts(root); return; }
      else return;
      draw(root);
    });
    root.addEventListener('input', function (e) {
      if (e.target.dataset.act === 'q') { root._ctd.q = e.target.value; fillPrompts(root); }
    });
  }

  function renderReport(root, rep) {
    if (!root._ctd) root._ctd = {cache: false, tab: 'overview', days: 3, bdw: 'today', q: '', sort: 'time'};
    root._rep = rep;
    if (!root._bound) { bind(root); root._bound = true; }
    draw(root);
  }

  window.CTD = {esc: esc, fmt: fmt, full: full, when: when, ago: ago, WLABEL: WLABEL, tot: tot, renderReport: renderReport};
})();
