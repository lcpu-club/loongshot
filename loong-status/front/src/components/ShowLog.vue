<template>
  <div class="log-container">
    <div class="log-toolbar">
      <div class="pager">
        <button
          class="btn"
          :disabled="loading || page <= 1"
          @click="loadPage(1)"
        >
          &laquo; First
        </button>
        <button
          class="btn"
          :disabled="loading || page <= 1"
          @click="loadPage(page - 1)"
        >
          &lsaquo; Prev
        </button>
        <input
          v-model.number="pageInput"
          class="page-input"
          type="number"
          min="1"
          :max="totalPages"
          @keyup.enter="jumpToPage"
        />
        <span class="page-total">/ {{ totalPages }}</span>
        <button
          class="btn"
          :disabled="loading || page >= totalPages"
          @click="loadPage(page + 1)"
        >
          Next &rsaquo;
        </button>
        <button
          class="btn"
          :disabled="loading || page >= totalPages"
          @click="loadPage(totalPages)"
        >
          Last &raquo;
        </button>
      </div>
      <span class="line-meta">{{ lineRange }}</span>
      <label class="switch">
        <input v-model="showLineNumbers" type="checkbox" />
        <span class="switch-track"><span class="switch-thumb"></span></span>
        <span>Line numbers</span>
      </label>
      <a class="download-link" :href="downloadUrl" download>Download raw log</a>
    </div>

    <div v-if="loading" class="log-status">Loading log...</div>
    <div v-else-if="error" class="error-message">{{ error }}</div>
    <pre v-else-if="renderedLog" v-html="renderedLog"></pre>
    <div v-else class="log-status">Log is empty.</div>
  </div>
</template>

<script>
import axios from "axios";
import { AnsiUp } from "ansi_up";
import DOMPurify from "dompurify";

const PAGE_SIZE = 1000;

export default {
  data() {
    return {
      page: 1,
      pageInput: 1,
      totalPages: 1,
      totalLines: 0,
      startLine: 0,
      rawLines: [],
      showLineNumbers: false,
      loading: false,
      error: null,
      requestSeq: 0,
    };
  },
  computed: {
    base() {
      return this.$route.query.base || "";
    },
    logName() {
      return this.$route.query.log_name || "";
    },
    downloadUrl() {
      const name = this.logName.replace(/\.log$/, "");
      return `/buildlogs/${encodeURIComponent(this.base)}/${encodeURIComponent(name)}.log`;
    },
    renderedLog() {
      return this.renderLines(
        this.rawLines,
        this.startLine,
        this.showLineNumbers,
      );
    },
    lineRange() {
      if (!this.totalLines) return "0 lines";
      const end = Math.min(this.startLine + PAGE_SIZE - 1, this.totalLines);
      return `lines ${this.startLine}-${end} of ${this.totalLines}`;
    },
  },
  watch: {
    "$route.query"() {
      this.loadPage(0);
    },
  },
  created() {
    this.loadPage(0);
  },
  methods: {
    async loadPage(page) {
      if (!this.base || !this.logName) {
        this.error = "Missing base or log_name query parameter.";
        return;
      }

      const seq = ++this.requestSeq;
      this.loading = true;
      this.error = null;

      try {
        const params = {
          base: this.base,
          log_name: this.logName,
          page_size: PAGE_SIZE,
        };
        if (page > 0) params.page = page;

        const response = await axios.get("/api/logs", { params });
        if (seq !== this.requestSeq) return;

        const data = response.data;
        this.page = data.page;
        this.pageInput = data.page;
        this.totalPages = data.total_pages;
        this.totalLines = data.total_lines;
        this.startLine = data.start_line;
        this.rawLines = data.lines || [];
      } catch (err) {
        if (seq !== this.requestSeq) return;
        console.error("Failed to fetch log:", err);
        this.error =
          "Failed to load log. Please check the URL or try again later.";
        this.rawLines = [];
      } finally {
        if (seq === this.requestSeq) this.loading = false;
      }
    },
    jumpToPage() {
      const page = Number(this.pageInput) || 1;
      this.loadPage(Math.min(Math.max(page, 1), this.totalPages));
    },
    renderLines(lines, startLine, showLineNumbers) {
      const converter = new AnsiUp();
      return lines
        .map((line, index) => {
          const html = DOMPurify.sanitize(converter.ansi_to_html(line));
          const gutter = showLineNumbers
            ? `<span class="line-number">${startLine + index}</span>`
            : "";
          return `<div class="log-line">${gutter}<span class="line-content">${html}</span></div>`;
        })
        .join("");
    },
  },
};
</script>

<style scoped>
.log-container {
  /* 默认跟随站点主题变量（浅色） */
  background-color: var(--color-background);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  font-family: "Fira Code", "Courier New", monospace;
  padding: 1rem;
  border-radius: 6px;
}

.log-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
  font-family: inherit;
}

.pager {
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn {
  width: 70px;
  font-size: 0.8rem;
  padding: 2px 4px;
  cursor: pointer;
}

.btn:disabled {
  cursor: default;
  opacity: 0.5;
}

.page-input {
  width: 60px;
  padding: 2px 4px;
  font-size: 0.8rem;
  text-align: right;
}

.page-total,
.line-meta {
  font-size: 0.8rem;
  color: var(--color-text-mute, #5c6370);
  white-space: nowrap;
}

.download-link {
  font-size: 0.8rem;
  color: var(--color-link, #2c7be5);
  padding: 0;
}

pre {
  white-space: normal;
  line-height: 1.5;
  margin: 0;
}

/* v-html 渲染的内容不带 scoped 属性，需要 :deep() 才能命中 */
pre :deep(.log-line) {
  display: flex;
  align-items: stretch;
  /* 空行也要占一行高度，否则竖线会被空行断开 */
  min-height: 1.5em;
}

pre :deep(.line-number) {
  flex: none;
  min-width: 4em;
  margin: 0;
  padding: 0 0.5em 0 0.25em;
  border-right: 1px solid var(--color-border, #d0d7de);
  background: var(--color-background-mute, #f1f0f1);
  color: var(--color-text-mute, #5c6370);
  text-align: right;
  white-space: pre;
  user-select: none;
}

pre :deep(.line-content) {
  flex: 1 1 auto;
  min-width: 0;
  padding: 0 0 0 0.75em;
  white-space: pre-wrap;
  word-break: break-word;
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  cursor: pointer;
  user-select: none;
}

.switch input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
}

.switch-track {
  position: relative;
  flex: none;
  width: 30px;
  height: 16px;
  border-radius: 8px;
  background: color-mix(
    in srgb,
    var(--color-text-mute, #5c6370) 35%,
    transparent
  );
  transition: background 0.15s;
}

.switch-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.15s;
}

.switch input:checked + .switch-track {
  background: var(--color-link, #2c7be5);
}

.switch input:checked + .switch-track .switch-thumb {
  transform: translateX(14px);
}

.switch input:focus-visible + .switch-track {
  outline: 2px solid var(--color-link, #2c7be5);
  outline-offset: 2px;
}

.log-status {
  color: var(--color-text-mute, #5c6370);
  padding: 1rem;
}

.error-message {
  color: var(--color-error, #c0392b);
  padding: 1rem;
  border: 1px solid
    color-mix(in srgb, var(--color-error, #c0392b) 35%, transparent);
  background: color-mix(in srgb, var(--color-error, #c0392b) 8%, transparent);
  border-radius: 4px;
}

/* 暗色模式：沿用原 One Dark 观感 */
@media (prefers-color-scheme: dark) {
  .log-container {
    background-color: var(--color-background);
    color: var(--color-text);
    border-color: var(--color-border);
  }

  .page-total,
  .line-meta,
  .log-status {
    color: var(--vt-c-text-dark-2);
  }

  pre :deep(.line-number) {
    background: var(--color-background-soft);
  }

  .download-link {
    color: #61afef;
  }

  .error-message {
    color: #e06c75;
    border-color: #e06c7555;
    background: #e06c7510;
  }
}
</style>
