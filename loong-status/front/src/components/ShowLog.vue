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
      renderedLog: "",
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
        this.renderedLog = this.renderLines(data.lines, data.start_line);
      } catch (err) {
        if (seq !== this.requestSeq) return;
        console.error("Failed to fetch log:", err);
        this.error =
          "Failed to load log. Please check the URL or try again later.";
        this.renderedLog = "";
      } finally {
        if (seq === this.requestSeq) this.loading = false;
      }
    },
    jumpToPage() {
      const page = Number(this.pageInput) || 1;
      this.loadPage(Math.min(Math.max(page, 1), this.totalPages));
    },
    renderLines(lines, startLine) {
      const converter = new AnsiUp();
      return lines
        .map((line, index) => {
          const html = DOMPurify.sanitize(converter.ansi_to_html(line));
          return `<span class="line-number">${startLine + index}</span>${html}`;
        })
        .join("\n");
    },
  },
};
</script>

<style scoped>
.log-container {
  background-color: #282c34;
  color: #abb2bf;
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
  color: #5c6370;
  white-space: nowrap;
}

.download-link {
  font-size: 0.8rem;
  color: #61afef;
  padding: 0;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  margin: 0;
}

.line-number {
  color: #5c6370;
  display: inline-block;
  min-width: 4em;
  padding-right: 0.75em;
  text-align: right;
  user-select: none;
  opacity: 0.6;
}

.log-status {
  color: #5c6370;
  padding: 1rem;
}

.error-message {
  color: #e06c75;
  padding: 1rem;
  border: 1px solid #e06c7555;
  background: #e06c7510;
  border-radius: 4px;
}
</style>
