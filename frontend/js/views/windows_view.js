window.SB_VIEWS = window.SB_VIEWS || {};
window.SB_VIEWS["windows-view"] = {
  template: `
  <div class="panel">
    <h2>时段窗</h2>
    <p class="lead">限制清单在哪些钟点与星期可上屏。星期集合即求值门限真值：求值星期不在集合内一律空播。</p>
    <table>
      <thead><tr><th>编码</th><th>标题</th><th>起止</th><th>星期集合（门限）</th><th>状态</th><th>门限</th></tr></thead>
      <tbody>
        <tr v-for="w in items" :key="w.id">
          <td>{{ w.code }}</td><td>{{ w.title }}</td>
          <td>{{ w.start_hm }} — {{ w.end_hm }}</td>
          <td><strong>{{ w.weekdays }}</strong></td>
          <td>{{ w.status }}</td>
          <td>
            <span class="badge" v-if="w.status === 'open'">开放门限</span>
            <span class="badge bad" v-else>门限停用</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>`,
  data() { return { items: [] }; },
  async mounted() { this.items = (await SB.api("/api/windows")).items; }
};
