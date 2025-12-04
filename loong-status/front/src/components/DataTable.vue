<template>
  <div class="page-container">
    <div class="header-container">
      <!-- Return button -->
      <router-link to="/" class="nav-button home-button">
        <svg class="icon" viewBox="0 0 24 24">
          <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" />
        </svg>
      </router-link>

      <div class="search-container">
        <div class="search-group">
          <!-- Input box-->
          <input
            v-model="searchName"
            placeholder="Search packages..."
            @keyup.enter="onSearch"
            class="search-input"
          />
          <!-- Filter button -->
          <div class="filter-wrapper">
            <button class="filter-btn" @click="toggleFilter">
              <svg class="filter-icon" viewBox="0 0 24 24">
                <path
                  d="M4 21h16v-2H4v2zm0-4h16v-2H4v2zm0-4h16v-2H4v2zm0-4h16V7H4v2zm0-4h16V3H4v2z"
                />
              </svg>
            </button>

            <!-- Filter menu -->
            <div v-show="showFilter" class="filter-panel">
              <div
                v-for="(label, index) in filterOptions"
                :key="label"
                class="filter-item"
                :class="{ active: selectedErrorType === label }"
                @click="selectFilter(index)"
              >
                {{ label }}
              </div>
            </div>
          </div>
          <button @click="onSearch" class="search-btn">
            <svg class="search-icon" viewBox="0 0 24 24">
              <path
                d="M15.5 14h-.79l-.28-.27a6.5 6.5 0 1 0-.7.7l.27.28v.79l5 5 1.5-1.5-5-5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
    <div class="main-content">
      <!-- Package data displaying table -->
      <div
        class="table-container"
        ref="tableContainer"
        :class="{ 'no-data': !total }"
      >
        <div class="flat-stats-bar">
          <div class="stat-cell">
            <span class="stat-number">{{ total }} packages found </span>
          </div>
        </div>

        <div
          class="table-scroll-container"
          :style="{ maxHeight: tableHeight + 'px' }"
        >
          <table>
            <colgroup>
              <col
                v-for="(col, index) in columnWidths"
                :key="index"
                :style="{ width: col.width }"
              />
            </colgroup>
            <thead>
              <tr>
                <th v-for="column in columns" :key="column">
                  <div
                    class="column-header"
                    @click="column === 'Repo' ? toggleRepoFilter() : null"
                    :class="{ clickable: column === 'Repo' }"
                  >
                    {{ column }}
                    <span
                      v-if="column === 'Repo'"
                      class="repo-filter-dropdown"
                      v-show="showRepoFilter"
                    >
                      <ul>
                        <li @click.stop="filterRepo('')">All</li>
                        <li @click.stop="filterRepo('extra')">Extra</li>
                        <li @click.stop="filterRepo('core')">Core</li>
                      </ul>
                    </span>
                    <!-- Status Legend -->
                    <span v-if="column === 'Status'" class="help-tooltip">
                      [?]
                      <div class="tooltip-content">
                        <div v-for="item in legendItems" :key="item.symbol">
                          <span :style="item.style">{{ item.symbol }}</span
                          >: {{ item.description }}
                        </div>
                      </div>
                    </span>
                  </div>
                </th>
              </tr>
            </thead>
            <tbody v-if="tableData.length">
              <tr v-for="row in tableData" :key="row.id">
                <td
                  v-for="column in columns"
                  :key="column"
                  v-html="row[column]"
                ></td>
              </tr>
            </tbody>
            <tbody v-else>
              <tr class="empty-row">
                <td :colspan="columns.length">
                  <div class="empty-message">No packages found</div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Page button -->
    <div class="paginator">
      <button
        class="page-arrow"
        @click="prevPage"
        :disabled="currentPage === 1"
      >
        &lt;
      </button>

      <div class="page-input">
        <input
          v-model.number="currentPage"
          type="number"
          min="1"
          :max="totalPages"
          @keyup.enter="goToSpecificPage"
        />
        <span>of {{ totalPages }}</span>
      </div>

      <button
        class="page-arrow"
        @click="nextPage"
        :disabled="currentPage >= totalPages"
      >
        &gt;
      </button>
    </div>
  </div>
</template>

<script>
import { useRoute } from "vue-router";
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from "vue";
import axios from "axios";

export default {
  setup() {
    const tableDataRaw = ref([]);
    const total = ref(0);
    const perPage = ref(20);
    const currentPage = ref(1);
    const searchName = ref("");
    const selectedErrorType = ref("");
    const showRepoFilter = ref(false);
    const selectedRepo = ref("");
    const route = useRoute();
    const showFilter = ref(false);

    // Auto adjust table size
    const tableContainer = ref(null);
    const tableHeight = ref(600);
    const autoPageSize = ref(50);

    const columns = ref([
      "Name",
      "Base",
      "Repo",
      "x86 Version",
      "Loong Version",
      "Status",
    ]);
    const filterOptions = ref([
      "All packages",
      "All failed builds",
      "Fail to apply loong's patch",
      "Unknown error before build",
      "Fail to download source",
      "Fail to pass the validity check",
      "Fail to pass PGP check",
      "Could not resolve all dependencies",
      "Failed in prepare",
      "Failed in build",
      "Failed in check",
      "Failed in package",
      "Cannot guess build type",
    ]);

    function compareVersions(loongVersion, x86Version) {
      if (!loongVersion || !x86Version || loongVersion === "missing")
        return false;
      const [loong_pkgver, loong_rel] = loongVersion.split("-");
      const loong_relver = loong_rel.split(".")[0];
      const [x86_pkgver, x86_relver] = x86Version.split("-");
      return loong_pkgver === x86_pkgver && loong_relver === x86_relver;
    }

    function compareAll(item) {
      let x86 = item.x86_version;
      let loong = item.loong_version;
      let testing = item.loong_testing_version;
      let staging = item.loong_staging_version;
      let flags = item.flags;
      let status;

      if (!x86 && (loong || testing || staging)) {
        status = "🗑";
      } else if (!loong && !testing && !staging) {
        status = "❌";
      } else if (compareVersions(loong, x86)) {
        status = "✅";
      } else {
        status = "⭕";
      }

      status += "&nbsp";
      if (flags) {
        if (flags & 1)
          status += `<span><a href="https://github.com/lcpu-club/loongarch-packages/tree/master/${item.base}" style="color: lime;">🅿</a></span>`;
        if (flags & 2) status += '<span style="color: blue;">🅲</span>';
        if (flags & 4) status += '<span style="color: orange;">🅾</span>';
        if (flags & 16)
          status += `<span><a href="log.html?url=/buildlogs/${item.base}/all.log" style="color: gold;">🅻</a></span>`;
        if (flags & (1 << 15))
          status += `<span title="${filterOptions[flags >> (16 - 1)]}" style="cursor: pointer; color: red;">🅵</span>`;
      }
      return status;
    }

    function mergeVersion(stable, testing, staging) {
      let merge = stable ? stable : "N/A";
      if (testing) merge += `\n${testing}🄣`;
      if (staging) merge += `\n${staging}🄢`;
      return merge;
    }

    const fetchData = async () => {
      try {
        const response = await axios.get("/api/packages/data", {
          params: {
            page: currentPage.value,
            per_page: perPage.value,
            name: searchName.value,
            error_type: selectedErrorType.value,
            repo: selectedRepo.value,
          },
        });
        tableDataRaw.value = response.data;
        total.value = response.data[0].total_count;
      } catch (error) {
        console.error("Error fetching data:", error);
      }
    };

    const tableData = computed(() =>
      tableDataRaw.value.map((item) => ({
        Name: item.name,
        Base: item.base,
        Repo: item.repo,
        "x86 Version": mergeVersion(
          item.x86_version,
          item.x86_testing_version,
          item.x86_staging_version,
        ),
        "Loong Version": mergeVersion(
          item.loong_version,
          item.loong_testing_version,
          item.loong_staging_version,
        ),
        Status: compareAll(item),
      })),
    );

    // Auto page size calculation
    const calculateAutoPageSize = () => {
      if (tableContainer.value) {
        const containerRect = tableContainer.value.getBoundingClientRect();

        const paginator = document.querySelector(".paginator");
        const paginatorHeight = paginator
          ? paginator.getBoundingClientRect().height
          : 60;
        const bottomMargin = 20;

        const availableHeight =
          window.innerHeight -
          containerRect.top -
          paginatorHeight -
          bottomMargin;

        // Table container height
        const statsBarHeight = 43;
        tableHeight.value = Math.max(400, availableHeight - statsBarHeight);

        const rowHeight = 45; // From CSS estimation
        const headerHeight = 50; // From CSS estimation

        const usableHeight = tableHeight.value - headerHeight;
        const visibleRows = Math.floor(usableHeight / rowHeight);

        autoPageSize.value = Math.max(10, Math.min(100, visibleRows));
      }
    };

    // Handle page size change
    const handlePageSizeChange = () => {
      currentPage.value = 1;
      fetchData();
    };

    // Handle window resize
    const handleResize = () => {
      calculateAutoPageSize();
      perPage.value = autoPageSize.value;
      fetchData();
    };

    const prevPage = () => {
      if (currentPage.value > 1) {
        currentPage.value--;
        fetchData();
      }
    };

    const nextPage = () => {
      if (currentPage.value < totalPages.value) {
        currentPage.value++;
        fetchData();
      }
    };

    const goToSpecificPage = () => {
      currentPage.value = Math.max(
        1,
        Math.min(currentPage.value, totalPages.value),
      );
      fetchData();
    };

    const totalPages =
      computed(() => Math.ceil(total.value / perPage.value)) || 1;

    // Close dropdown when clicking outside
    const handleClickOutside = (event) => {
      const filterPanel = document.querySelector(".filter-panel");
      const filterBtn = document.querySelector(".filter-btn");
      const repoDropdown = document.querySelector(".repo-filter-dropdown");
      const repoBtn = document.querySelector(".clickable");

      const clickedOutside = (box, btn) => {
        const target = event.target;
        // Not in the filter panel or button
        return box && !box.contains(target) && (!btn || !btn.contains(target));
      };

      if (showFilter.value && clickedOutside(filterPanel, filterBtn)) {
        showFilter.value = false;
        console.log("Close filter");
      }

      if (showRepoFilter.value && clickedOutside(repoDropdown, repoBtn)) {
        showRepoFilter.value = false;
        console.log("Close repo filter");
      }
    };

    onMounted(() => {
      document.addEventListener("click", handleClickOutside);
      window.addEventListener("resize", handleResize);

      searchName.value = route.query.name?.trim() || null;
      selectedErrorType.value = route.query.error_type?.trim() || null;
      selectedRepo.value = route.query.repo?.trim() || null;

      // Initial page size calculation
      nextTick().then(() => {
        calculateAutoPageSize();
        perPage.value = autoPageSize.value;
        fetchData();
      });
    });

    onBeforeUnmount(() => {
      document.removeEventListener("click", handleClickOutside);
    });

    const onSearch = () => {
      currentPage.value = 1;
      fetchData();
    };

    const toggleFilter = () => {
      showFilter.value = !showFilter.value;
    };

    const toggleRepoFilter = () => {
      showRepoFilter.value = !showRepoFilter.value;
    };

    const selectFilter = (index) => {
      selectedErrorType.value = index;
      showFilter.value = false;
      fetchData();
    };

    const filterRepo = (repo) => {
      selectedRepo.value = repo?.trim() || null;
      showRepoFilter.value = !showRepoFilter.value;
      fetchData();
    };

    return {
      tableData,
      columns,
      totalPages,
      currentPage,
      searchName,
      selectedErrorType,
      total,
      perPage,
      autoPageSize,
      tableHeight,
      tableContainer,
      fetchData,
      nextPage,
      prevPage,
      goToSpecificPage,
      handlePageSizeChange,
      toggleFilter,
      showFilter,
      selectFilter,
      filterOptions,
      filterRepo,
      showRepoFilter,
      toggleRepoFilter,
      onSearch,
    };
  },
  data() {
    return {
      legendItems: [
        {
          symbol: "✅",
          description: "loong's version matches x86's",
          style: "",
        },
        { symbol: "⭕", description: "loong's version mis-matches", style: "" },
        {
          symbol: "❌",
          description: "missing this package in loong",
          style: "",
        },
        { symbol: "🗑", description: "missing this package in x86", style: "" },
        {
          symbol: "🅿",
          description: "has patch in our repo",
          style: "color: lime;",
        },
        {
          symbol: "🅻",
          description: "has build log on server",
          style: "color: gold;",
        },
        {
          symbol: "🅲",
          description: "build with nocheck",
          style: "color: blue;",
        },
        {
          symbol: "🅾",
          description: "config.sub is too old",
          style: "color: orange;",
        },
        { symbol: "🅵", description: "build fails", style: "color: red;" },
        { symbol: "🅱︎", description: "in blacklist", style: "color: black;" },
      ],
    };
  },
};
</script>
<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: var(--color-background);
}

.header-container {
  flex-shrink: 0;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #9b2d35;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  position: relative;
  z-index: 100;
  min-height: 60px;
  gap: 20px;
  border-radius: 8px 8px 0 0;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 20px; /* Added padding for better spacing */
}

.nav-button {
  width: 40px;
  height: 40px;
  padding: 8px;
  border: none;
  border-radius: 8px;
  background: #8b2830;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.nav-button:hover,
.search-btn:hover,
.filter-btn:hover {
  background: #6b2024;
}

.icon {
  width: 24px;
  height: 24px;
  fill: white;
}
.search-container {
  width: 50%;
  min-width: 400px;
}
.search-group {
  display: flex;
  align-items: stretch;
  background: #8b2830;
  border-radius: 35px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
}
.search-input {
  flex: 1;
  height: 50px;
  padding: 0 25px;
  border: none;
  background: transparent;
  font-size: 16px;
  color: white;
}
.search-input::placeholder {
  color: rgba(255, 255, 255, 0.7);
}
.search-input:focus {
  outline: none;
}
.search-btn,
.filter-btn {
  border: none;
  cursor: pointer;
  background: #8b2830;
  display: flex;
  align-items: center;
  justify-content: center;
}
.search-btn {
  width: 60px;
  height: 50px;
  border-radius: 0 35px 35px 0;
}
.filter-btn {
  height: 50px;
  padding: 0 12px;
}
.search-icon,
.filter-icon {
  fill: white;
  width: 20px;
  height: 20px;
}
.filter-wrapper {
  position: relative;
}

/* === POP-UP PANELS === */
.filter-panel,
.tooltip-content,
.repo-filter-dropdown {
  position: absolute;
  background-color: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  z-index: 1000;
  transition:
    opacity 0.2s,
    background-color 0.3s,
    border-color 0.3s;
}

.filter-panel {
  top: 100%;
  right: 0;
  width: 240px;
  margin-top: 8px;
}
.filter-item {
  padding: 10px 16px;
  cursor: pointer;
  border-bottom: 1px solid var(--color-border);
}
.filter-item:last-child {
  border-bottom: none;
}
.filter-item:hover {
  background-color: var(--color-background-mute);
}
.filter-item.active {
  background: #9b2d35;
  color: white;
  font-weight: 500;
}

/* === STATS BAR === */
.flat-stats-bar {
  display: flex;
  align-items: center;
  background-color: var(--color-background-soft);
  border: 1px solid var(--color-border);
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  padding: 8px 16px;
}
.stat-number {
  font-weight: 600;
  color: var(--color-text);
}

/* === TABLE === */
.table-scroll-container {
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: 0 0 8px 8px;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: 12px 15px; /* Increased padding */
  text-align: left;
  border-bottom: 1px solid var(--color-border);
  white-space: nowrap;
}
thead {
  position: sticky;
  top: 0;
  z-index: 2;
}
th {
  background-color: var(--color-background-soft);
  color: var(--color-heading);
  font-weight: 600;
}
tr:hover {
  background-color: var(--color-background-mute);
}
.empty-row td {
  height: 150px;
  text-align: center;
}
.empty-message {
  color: var(--color-text);
  opacity: 0.7;
}

/* === PAGINATOR === */
.paginator {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 15px;
  padding: 20px;
  border-top: 1px solid var(--color-border);
}
.page-arrow {
  width: 40px;
  height: 40px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background-color: var(--color-background-soft);
  color: var(--color-text);
  cursor: pointer;
  font-weight: bold;
  transition: all 0.2s;
}
.page-arrow:hover:not(:disabled) {
  border-color: var(--color-border-hover);
  background-color: var(--color-background-mute);
}
.page-arrow:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.page-input input {
  width: 60px;
  height: 40px;
  padding: 0 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  text-align: center;
  background-color: var(--color-background);
  color: var(--color-text);
  -moz-appearance: textfield;
}
.page-input span {
  color: var(--color-text);
  opacity: 0.7;
  font-size: 0.9em;
  margin-left: 8px;
}

/* === TOOLTIP & DROPDOWN === */
.help-tooltip {
  cursor: help;
  position: relative;
}
.help-tooltip:hover .tooltip-content {
  visibility: visible;
  opacity: 1;
}
.tooltip-content {
  visibility: hidden;
  opacity: 0;
  top: 100%;
  left: 50%;
  transform: translateX(-50%) translateY(8px);
  padding: 12px;
  min-width: 240px;
}
.column-header.clickable {
  cursor: pointer;
}
.repo-filter-dropdown {
  top: 100%;
  left: 0;
}
.repo-filter-dropdown ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.repo-filter-dropdown li {
  padding: 8px 12px;
  cursor: pointer;
}
.repo-filter-dropdown li:hover {
  background-color: var(--color-background-mute);
}

/* Dark mode specific tweaks for shadows that look better */
@media (prefers-color-scheme: dark) {
  .filter-panel,
  .tooltip-content,
  .repo-filter-dropdown {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  }
}

@media (max-width: 768px) {
  .header-container {
    padding: 8px 12px;
    min-height: 52px;
  }

  .search-container {
    width: 60%;
    min-width: 300px;
  }

  .search-group {
    border-radius: 25px;
  }

  .search-input {
    padding: 0 15px;
    font-size: 14px;
  }

  .filter-panel {
    width: 200px;
    right: -50%;
  }

  .tooltip-content {
    min-width: 200px;
    font-size: 0.9em;
  }

  .nav-button {
    width: 36px;
    height: 36px;
  }

  .paginator {
    gap: 10px;
    padding: 15px;
  }

  .page-arrow {
    width: 35px;
    height: 35px;
  }
}
</style>
