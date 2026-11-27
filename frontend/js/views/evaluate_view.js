window.SB_VIEWS = window.SB_VIEWS || {};
window.SB_VIEWS["evaluate-view"] = {
  template: `
  <div class="panel">
    <h2>在线求值</h2>
    <p class="lead">给定屏幕与时刻，计算应播内容（覆盖优先）。求值星期不在时段窗星期集合内即正式空播并记拒播痕。</p>
    <div class="row-form">
      <input v-model.number="screen_id" type="number" placeholder="屏幕ID" />
      <input v-model="now_hm" placeholder="HH:MM" />
      <input v-model="weekday" placeholder="星期1-7" />
      <button class="primary" @click="run">求值</button>
    </div>
    <div class="row-form" v-if="result">
      <span class="badge bad" v-if="result.gate_status === 'rejected_weekday'">星期不匹配 · 正式空播</span>
      <span class="badge warn" v-else-if="result.gate_status === 'outside_window'">钟点不在窗内 · 空播</span>
      <span class="badge warn" v-else-if="result.gate_status === 'no_publication'">无正式发布 · 空播</span>
      <span class="badge" v-else-if="result.gate_status === 'played'">命中 · 播放清单</span>
      <span class="badge" v-else-if="result.gate_status === 'override'">覆盖优先</span>
      <span class="muted" v-if="result.window_weekdays">窗星期集合：{{ result.window_weekdays }} ｜ 求值星期：{{ result.weekday }}</span>
      <span class="muted" v-if="result.ledger_id">正式结果册 #{{ result.ledger_id }}</span>
    </div>
    <p class="err" v-if="blankReason">{{ blankReason }}</p>
    <pre style="white-space:pre-wrap;background:#0d1828;padding:12px;border-radius:10px;">{{ resultText }}</pre>
    <p class="err" v-if="error">{{ error }}</p>
  </div>`,
  data() {
    return { screen_id: 1, now_hm: "10:30", weekday: "1", result: null, resultText: "", error: "" };
  },
  computed: {
    blankReason() {
      if (this.result && this.result.play === null && this.result.reason) return "空播原因：" + this.result.reason;
      return "";
    }
  },
  methods: {
    async run() {
      this.error = "";
      try {
        const r = await SB.api("/api/evaluate/screen", {
          method: "POST",
          body: JSON.stringify({ screen_id: this.screen_id, now_hm: this.now_hm, weekday: this.weekday })
        });
        this.result = r;
        this.resultText = JSON.stringify(r, null, 2);
      } catch (e) {
        this.result = null;
        this.error = e.message;
      }
    }
  }
};
