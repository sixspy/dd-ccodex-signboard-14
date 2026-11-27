window.SB_VIEWS = window.SB_VIEWS || {};
window.SB_VIEWS["history-view"] = {
  template: `
  <div class="panel">
    <h2>变更历史</h2>
    <p class="lead">发布、撤屏、覆盖与台账变更同源可追溯；星期不匹配空播在此留 reject_weekday 拒播痕。</p>
    <div class="row-form">
      <button class="ghost" @click="onlyRejects = !onlyRejects">
        {{ onlyRejects ? '显示全部' : '只看星期拒播痕' }}
      </button>
      <span class="badge bad" v-if="rejectCount">拒播痕 {{ rejectCount }}</span>
    </div>
    <table>
      <thead><tr><th>ID</th><th>实体</th><th>动作</th><th>详情</th><th>操作者</th><th>门限</th></tr></thead>
      <tbody>
        <tr v-for="h in shown" :key="h.id">
          <td>{{ h.id }}</td><td>{{ h.entity_kind }}#{{ h.entity_id }}</td>
          <td><span class="badge" :class="h.action === 'reject_weekday' ? 'bad' : ''">{{ h.action }}</span></td>
          <td>{{ h.detail }}</td><td>{{ h.actor }}</td>
          <td>
            <span class="badge bad" v-if="h.action === 'reject_weekday'">正式空播</span>
            <span class="badge" v-else>常规变更</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>`,
  data() { return { items: [], onlyRejects: false }; },
  computed: {
    shown() { return this.onlyRejects ? this.items.filter(h => h.action === "reject_weekday") : this.items; },
    rejectCount() { return this.items.filter(h => h.action === "reject_weekday").length; }
  },
  async mounted() { await this.reload(); },
  methods: {
    async reload() { this.items = (await SB.api("/api/history")).items; }
  }
};
