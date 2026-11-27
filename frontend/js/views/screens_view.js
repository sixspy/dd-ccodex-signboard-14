window.SB_VIEWS = window.SB_VIEWS || {};
window.SB_VIEWS["screens-view"] = {
  template: `
  <div class="panel">
    <h2>屏幕台账</h2>
    <p class="lead">物理终端绑定分区、分辨率与在线状态；末列展示最近一次在线求值门限，拒播显红、不假绿。</p>
    <table>
      <thead><tr><th>编码</th><th>标题</th><th>分区</th><th>分辨率</th><th>状态</th><th>风险</th><th>最近求值门限</th></tr></thead>
      <tbody>
        <tr v-for="s in items" :key="s.id">
          <td>{{ s.code }}</td><td>{{ s.title }}</td><td>{{ s.zone_title }}</td>
          <td>{{ s.resolution }}</td>
          <td><span class="badge" :class="s.status==='online'?'':(s.status==='maintenance'?'bad':'warn')">{{ s.status_label }}</span></td>
          <td>{{ s.risk_level }}</td>
          <td>
            <span class="badge bad" v-if="s.last_eval_gate === 'rejected_weekday'">
              星期拒播·空播（周{{ s.last_eval_weekday }}）
            </span>
            <span class="badge warn" v-else-if="s.last_eval_gate === 'outside_window'">钟点窗外·空播</span>
            <span class="badge warn" v-else-if="s.last_eval_gate === 'no_publication'">无正式发布</span>
            <span class="badge" v-else-if="s.last_eval_gate === 'played'">命中播放（周{{ s.last_eval_weekday }}）</span>
            <span class="badge warn" v-else-if="s.last_eval_gate === 'override'">覆盖优先</span>
            <span class="muted" v-else>尚未求值</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>`,
  data() { return { items: [] }; },
  async mounted() { this.items = (await SB.api("/api/screens")).items; }
};
