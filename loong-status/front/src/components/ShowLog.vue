<template>
  <div class="log-container">
    <h2>Log Details</h2>
    <div v-if="loading">Loading log...</div>
    <div v-if="error" class="error-message">{{ error }}</div>
    <pre v-if="!loading && !error" v-html="parsedLogContent"></pre>
  </div>
</template>

<script>
import axios from "axios";
import * as ansi_up from "ansi_up";
import DOMPurify from "dompurify";

export default {
  data() {
    return {
      logContent: "",
      parsedLogContent: "",
      loading: false,
      error: null,
    };
  },
  created() {
    this.fetchLog();
  },
  methods: {
    async fetchLog() {
      this.loading = true;
      this.error = null;
      const { base, log_name } = this.$route.query;

      try {
        const response = await axios.get(`/api/logs`, {
          params: { base, log_name },
        });
        this.logContent = response.data;

        const converter = new ansi_up.AnsiUp();

        // Add line numbers
        this.parsedLogContent = this.logContent
          .split("\n")
          .map((line, index) => {
            const htmlLine = converter.ansi_to_html(line);
            const safeLine = DOMPurify.sanitize(htmlLine);
            return `<span class="line-number">${index + 1}</span>  ${safeLine}`;
          })
          .join("\n");
      } catch (err) {
        console.error("Failed to fetch log:", err);
        this.error =
          "Failed to load log. Please check the URL or try again later.";
      } finally {
        this.loading = false;
      }
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

pre {
  white-space: pre-wrap;
  line-height: 1.5;
  margin: 0;
}

.line-number {
  color: #5c6370;
  display: inline-block;
  width: 3em;
  user-select: none;
  opacity: 0.6;
}

.error-message {
  color: #e06c75;
  padding: 1rem;
  border: 1px solid #e06c7555;
  background: #e06c7510;
  border-radius: 4px;
}
</style>
