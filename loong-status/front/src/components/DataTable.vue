<template>
  <div class="page-container">
  <div class="header-container">
    <!-- Return button -->
    <router-link to="/" class="nav-button home-button">
      <svg class="icon" viewBox="0 0 24 24">
        <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/>
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
              <path d="M4 21h16v-2H4v2zm0-4h16v-2H4v2zm0-4h16v-2H4v2zm0-4h16V7H4v2zm0-4h16V3H4v2z"/>
            </svg>
          </button>
          
          <!-- Filter menu -->
          <div v-show="showFilter" class="filter-panel">
            <div 
              v-for="label in filterOptions"
              :key="label" 
              class="filter-item"
              :class="{ active: selectedErrorType === label }"
              @click="selectFilter(label)"
            >
              {{ label }}
            </div>
          </div>
        </div>
      <button @click="onSearch" class="search-btn">
        <svg class="search-icon" viewBox="0 0 24 24">
          <path d="M15.5 14h-.79l-.28-.27a6.5 6.5 0 1 0-.7.7l.27.28v.79l5 5 1.5-1.5-5-5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z"/>
        </svg>
      </button>
    </div>
  </div>
  
    <!-- Current building list sidebar -->
    <button class="nav-button task-button" @click="toggleSidebar">
      <svg class="sidebar-icon" viewBox="0 0 24 24">
        <path d="M4 18h16c.55 0 1-.45 1-1s-.45-1-1-1H4c-.55 0-1 .45-1 1s.45 1 1 1zm0-5h16c.55 0 1-.45 1-1s-.45-1-1-1H4c-.55 0-1 .45-1 1s.45 1 1 1zM3 7c0 .55.45 1 1 1h16c.55 0 1-.45 1-1s-.45-1-1-1H4c-.55 0-1 .45-1 1z"/>
      </svg>
    </button>
    <div class="sidebar" :class="{ active: isSidebarOpen }">
      <div class="sidebar-header">
        <h3>Building Tasks</h3>
        <button class="close-btn" @click="toggleSidebar">&times;</button>
      </div>
      <div class="sidebar-content">
        <div v-if="activeTask" class="current-task">
        Current building task: #{{activeTask.task_no}} {{ activeTask.name }} 
        </div>
        <div v-if="loading" class="loading">Loading...</div>
        <div v-else-if="error" class="error">{{ error }}</div>
        <div v-else>
          <table class="sidebar-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Name</th>
            <th>Base</th>
            <th>Repo</th>
          </tr>
        </thead>
        <tbody>
          <tr 
            v-for="(task, index) in buildingTasks" 
            :key="task.id"
            :class="{ 'processing': task.status === 'Building' }"
          >
            <td>{{ index + 1 }}</td>
            <td class="text-ellipsis">{{ task.name }}</td>
            <td>{{ task.base }}</td>
            <td>{{ task.repo }}</td>
          </tr>
        </tbody>
      </table>
        </div>
      </div>
    </div>
    <!-- Sidebar overlay -->
    <div v-if="isSidebarOpen" class="sidebar-overlay" @click="toggleSidebar"></div>
  </div>
  <div class="main-content">
  <!-- Package data displaying table -->
  <div class="table-container" :class="{ 'no-data': !total }">
    <div class="flat-stats-bar">
    <div class="stat-cell">
      <span class="stat-number">{{ total }} packages found </span>
    </div>
  </div>

    <table>      
        <colgroup>
        <col v-for="(col, index) in columnWidths" 
            :key="index" 
            :style="{ width: col.width }">
      </colgroup>
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">
              <div class="column-header"
              @click="column === 'Repo' ? toggleRepoFilter() : null"
               :class="{ 'clickable': column === 'Repo' }"
              >
                {{ column }}
                <span v-if="column === 'Repo'" class="repo-filter-dropdown" v-show="showRepoFilter">
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
                      <span :style="item.style">{{ item.symbol }}</span>: {{ item.description }}
                    </div>
                  </div>
                </span>
              </div>
            </th>
          </tr>
        </thead>
        <tbody v-if="tableData.length">
          <tr v-for="row in tableData" :key="row.id">
            <td v-for="column in columns" :key="column" v-html="row[column]"></td>
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
import { useRoute } from 'vue-router';
import { ref, reactive, computed, onMounted } from 'vue';
import axios from 'axios';

export default {
  setup() {
    const tableDataRaw = ref([]);
    const total = ref(0);
    const perPage = ref(20);
    const currentPage = ref(1);
    const searchName = ref('')
    const selectedErrorType = ref('')
    // const selectedStatus = ref('');
    const showRepoFilter = ref(false);
    const selectedRepo = ref('');
    const route = useRoute();
    const showFilter = ref(false);

    const columns = ref(['Name', 'Base', 'Repo', 'x86 Version', 'Loong Version', 'Status']);
    const filterOptions = ref([
    'All failed builds',
    'Fail to apply loong\'s patch',
    'Unknown error before build',
    'Fail to download source',
    'Fail to pass the validity check',
    'Fail to pass PGP check',
    'Could not resolve all dependencies',
    'Failed in prepare',
    'Failed in build',
    'Failed in check',
    'Failed in package',
    'Cannot guess build type'
    ]);

    function compareVersions(loongVersion, x86Version) {
      if (!loongVersion || !x86Version || loongVersion === 'missing') return false;
      const [loong_pkgver, loong_rel] = loongVersion.split('-')
      const loong_relver = loong_rel.split('.')[0]
      const [x86_pkgver, x86_relver] = x86Version.split('-')
      return (loong_pkgver === x86_pkgver) && (loong_relver === x86_relver);
    }

    function compareAll(item) {
      let x86 = item.x86_version;
      let loong = item.loong_version;
      let testing = item.loong_testing_version;
      let staging = item.loong_staging_version;
      let error_type = item.error_type;
      let status;

      if (x86 === 'missing') {
          status = '🗑';
      } else if (loong ==='missing') {
          status = '❌';
      } else if (compareVersions(loong, x86)) {
          status = '✅';
      } else {
          status = '⭕';
      }

      status += '&nbsp';
      if (item.has_log === true) {
        const encodedVersion = encodeURIComponent(item.loong_version);
        const logUrl = `/log?base=${item.base}&name=${item.name}&version=${encodedVersion}`;
        status += `<span><a href="${logUrl}" target="_blank" style="color: gold;">🅻</a></span>`;      
      } else {
        status += '<span style="color: gray;">🅻</span>';
      }

      if (item.is_blacklisted === true) {
        status += '<span style="color: black;">🅱︎</span>';
      }
      // if (flags) {
      //   if (flags & 1) status += `<span><a href="https://github.com/lcpu-club/loongarch-packages/tree/master/${item.base}" style="color: lime;">🅿</a></span>`;
      //   if (flags & 2) status += '<span style="color: blue;">🅲</span>';
      //   if (flags & 4) status += '<span style="color: orange;">🅾</span>';
      //   if (flags & 16) status += `<span><a href="log.html?url=/buildlogs/${item.base}/all.log" style="color: gold;">🅻</a></span>`;
      //   if (flags & (1 << 15)) status += `<span title="${fail_reason[flags >> 16 - 1]}" style="cursor: pointer; color: red;">🅵</span>`;
      // }
      return status;
    }

    function mergeVersion(stable, testing, staging) {
      let merge = stable ? stable: 'N/A';
      if (testing) merge += `\n${testing}🄣`;
      if (staging) merge += `\n${staging}🄢`;
      return merge;
    }

    const fetchData = async () => {
      try {
        const response = await axios.get('/api/packages/data', {
          params: {
            page: currentPage.value,
            per_page: perPage.value,
            name: searchName.value,
            error_type: selectedErrorType.value,
            repo: selectedRepo.value
          },
        });
        tableDataRaw.value = response.data.data;
        total.value = response.data.total;
      } catch (error) {
        console.error('Error fetching data:', error);
      }
    };

    const tableData = computed(() =>
      tableDataRaw.value.map(item => ({
        Name: item.name,
        Base: item.base,
        Repo: item.repo,
        has_log: item.has_log,
        is_blacklisted: item.is_blacklisted,
        'x86 Version': mergeVersion(item.x86_version, item.x86_testing_version, item.x86_staging_version),
        'Loong Version': mergeVersion(item.loong_version, item.loong_testing_version, item.loong_staging_version),
        Status: compareAll(item),
      }))
    );

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
      currentPage.value = Math.max(1, Math.min(currentPage.value, totalPages.value))
      fetchData();
    };

    const totalPages = computed(() => Math.ceil(total.value / perPage.value)) || 1;

    onMounted(() => {
      searchName.value = route.query.name?.trim() || null;
      selectedErrorType.value = route.query.error_type?.trim() || null;
      selectedRepo.value = route.query.repo?.trim() || null;
      fetchData();
    });

    // const onStatusChange = () => {
    //   if (selectedStatus.value === 'All') {
    //     searchQuery.value = ':fail';
    //   } else {
    //     searchQuery.value = `:code${selectedStatus.value}`;
    //   }
    //   onSearch();
    // };

    const onSearch = () => {
      currentPage.value = 1;
      fetchData();
    };

    const toggleFilter = () => {
      showFilter.value = !showFilter.value
    }

    const toggleRepoFilter = () => {
      showRepoFilter.value = !showRepoFilter.value;
    };

    const selectFilter = (label) => {
      label = label === 'All failed builds' ? 'Success' : label
      selectedErrorType.value = selectedErrorType.value === label ? null : label
      showFilter.value = false
      fetchData()
    }

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
      fetchData,
      nextPage,
      prevPage,
      goToSpecificPage,
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
      windowHeight: 0,
      rowHeight: 40,
      isSidebarOpen: false,
      buildingTasks: [],
      loading: false,
      error: null,
      activeTask:null,
      legendItems: [
      { symbol: '✅', description: 'loong\'s version matches x86\'s', style: '' },
      { symbol: '⭕', description: 'loong\'s version mis-matches', style: '' },
      { symbol: '❌', description: 'missing this package in loong', style: '' },
      { symbol: '🗑', description: 'missing this package in x86', style: '' },
      { symbol: '🅿', description: 'has patch in our repo', style: 'color: lime;' },
      { symbol: '🅻', description: 'has build log on server', style: 'color: gold;' },
      { symbol: '🅲', description: 'build with nocheck', style: 'color: blue;' },
      { symbol: '🅾', description: 'config.sub is too old', style: 'color: orange;' },
      { symbol: '🅵', description: 'build fails', style: 'color: red;' },
      { symbol: '🅱︎', description: 'in blacklist', style: 'color: black;' }
      ],
      columnWidths: [
          { width: '20%' },  
          { width: '20%' },
          { width: '5%' },
          { width: '20%' },
          { width: '20%' },
          { width: '15%' }
        ],
    };
    
  },
  computed: {
    visibleData() {
      const availableHeight = this.windowHeight - 200
      const visibleRows = Math.floor(availableHeight / this.rowHeight)
      return this.tableData.slice(0, visibleRows)
    }
  },
  mounted() {
    this.updateWindowSize()
    window.addEventListener('resize', this.updateWindowSize)
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.updateWindowSize)
  },
  methods: {
    updateWindowSize() {
      this.windowHeight = window.innerHeight
    },
    toggleSidebar() {
      this.isSidebarOpen = !this.isSidebarOpen;
      if (this.isSidebarOpen) {
        this.fetchBuildingTasks();
      }
    },
    async fetchBuildingTasks() {
      this.loading = true;
      this.error = null;
      try {
        const response = await fetch('/api/packages/building_list');
        if (!response.ok) throw new Error('Failed to fetch tasks');
        
        const tasks = await response.json();
        this.buildingTasks = tasks;

        this.activeTask = tasks.find(task => 
          task.status === "Building"
        ) || null;

      } catch (err) {
        this.error = err.message;
      } finally {
        this.loading = false;
      }
    },
  }
};
</script>
<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.header-container {
  flex-shrink: 0;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #9b2d35;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
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

.nav-button:hover {
  background: #6b2024;
}

.icon {
  width: 24px;
  height: 24px;
  fill: white;
}

.home-button .icon {
  transform: translateX(-2px);
}

/* Search box */
.search-container {
  position: static;
  /* left: 50%;
  top: 50%; */
  transform: none;
  width: 50%;
  min-width: 400px;
}

.search-group {
  display: flex;
  align-items: stretch;
  background: #8b2830;
  border-radius: 35px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.1);
  transition: all 0.3s ease;
}

.search-input {
  flex: 1;
  height: 50px;
  padding: 0 25px;
  border: none;
  background: transparent;
  font-size: 16px;
  border-radius: 35px 0 0 35px;
  color: white;
}

.search-input:focus {
  outline: none;
  box-shadow: none;
}

/* Search button */
.search-btn {
  width: 60px;
  height: 50px; 
  border: none;
  background: #8b2830;
  border-radius: 0 35px 35px 0;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.search-btn:hover {
  background: #6b2024;
}

/* Filter */
.filter-wrapper {
  position: relative;
  display: inline-block;
}

.filter-btn {
  height: 50px; 
  padding: 0 12px; 
  background: #8b2830;
  border: none;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.filter-btn:hover {
  background: #6b2024;
}

.filter-icon {
  width: 18px;
  height: 18px;
  fill: #666;
}

.filter-panel {
  position: absolute;
  top: 100%;
  right: 0;
  width: 240px;
  background: white;
  border: 1px solid #eee;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  margin-top: 8px;
  z-index: 1000;
  max-height: 400px;
  overflow-y: auto;
}

.filter-item {
  padding: 10px 16px;
  cursor: pointer;
  transition: all 0.2s;
  border-bottom: 1px solid #f8f9fa;
}

.filter-item:hover {
  background: #f5e4e5;
}

.filter-item.active {
  background: #e3f2fd;
  color: #6b2024;
  font-weight: 500;
}

.search-icon {
  width: 22px;
  height: 22px;
  fill: white;
}

.filter-icon {
  width: 20px;
  height: 20px;
  fill: white;
}

.paginator {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 15px;
  padding: 20px;
  margin-top: 20px;
  background: var(--bg-primary);
  border-top: 1px solid var(--border-color);
}

.page-arrow {
  width: 40px;
  height: 40px;
  border: 1px solid #ddd;
  border-radius: 8px;
  background: white;
  cursor: pointer;
  font-weight: bold;
  transition: all 0.2s;
}

.page-arrow:hover:not(:disabled) {
  border-color: #6b2024;
  color: #6b2024;
}

.page-arrow:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-input {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-input input {
  width: 60px;
  height: 40px;
  padding: 0 10px;
  border: 1px solid #ddd;
  border-radius: 8px;
  text-align: center;
  -moz-appearance: textfield;
  appearance: textfield;
  
  &::-webkit-outer-spin-button,
  &::-webkit-inner-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }
}

.page-input span {
  color: #666;
  font-size: 0.9em;
}

@media (max-width: 768px) {
  .header-container {
    padding: 8px 12px;
    min-height: 52px;
  }

  .search-container {
    width: 60%;
    min-width: 300px;
    top: 8px;
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
    left: 50%;
    transform: translateX(-50%);
  }

  .nav-button {
    width: 36px;
    height: 36px;
  }

  .sidebar-table thead {
    top: 60px; 
  }
  
  .sidebar-content {
    height: calc(100vh - 80px);
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

.column-header {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.help-tooltip {
  cursor: help;
  position: relative;
  color: #666;
  font-size: 0.8em;
  margin-left: 4px;
  
  &:hover .tooltip-content {
    visibility: visible;
    opacity: 1;
  }
}

.tooltip-content {
  visibility: hidden;
  opacity: 0;
  position: absolute;
  top: 100%;
  bottom: auto;
  left: 50%;
  transform: translateX(-50%) translateY(8px);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 12px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  min-width: 240px;
  z-index: 1000; 
  transition: opacity 0.2s;
  font-size: 14px;
  line-height: 1.6;
  text-align: left;
  
  div {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 4px 0;
  }
}

.task-button {
  background: #8b2830;
  
  .icon {
    fill: white;
  }
  
  &:hover {
    background: #6b2024;
  }
}

.sidebar {
  position: fixed;
  right: -1000px;
  top: 0;
  width: 1000px;
  height: 100%;
  min-width: 360px; 
  max-width: 90%; 
  background: white;
  box-shadow: -2px 0 5px rgba(0,0,0,0.2);
  transition: right 0.3s ease;
  z-index: 1001;
}

.sidebar:hover {
  background: #e9ecef;
}

.sidebar-icon {
  width: 24px;
  height: 24px;
  fill: white;
}

.sidebar.active {
  right: 0;
}

.sidebar-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0,0,0,0.5);
  z-index: 1000;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid #ddd;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
}

.sidebar-content {
  padding: 1rem;
  height: calc(100% - 60px);
  overflow-y: hidden;
}

.sidebar-table {
  width: 100%;
  height: 100%;
  table-layout: auto;
  min-width: 380px;
  border-collapse: collapse;
  overflow: visible;
  display: block; 
  scroll-behavior: smooth;
  th, td {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border-color);
    text-align: left;
  }

  th {
    font-weight: 500;
    background: var(--bg-secondary);
  }

  tr:hover {
    background: rgba(var(--accent-color-rgb), 0.05);
  }
}

.sidebar-table thead {
  display: table;
  width: 100%;
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg-primary);
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.sidebar-table tbody {
  display: block;
  overflow-y: auto;
  max-height: calc(100vh - 160px); 
}

.sidebar-table thead tr,
.sidebar-table tbody tr {
  display: table;
  width: 100%;
  table-layout: fixed;
}

.sidebar-table::-webkit-scrollbar {
  height: 6px;
  width: 6px;
}

.sidebar-table::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}

.task-item {
  padding: 0.5rem;
  margin-bottom: 0.5rem;
  border-bottom: 1px solid #eee;
}

.loading, .error {
  padding: 1rem;
  text-align: center;
}

.current-task {
  font-size: 0.9em;
  color: #666;
  padding: 8px 12px;
  background: #f5f5f5;
  border-radius: 4px;
  margin-bottom: 12px;
}

tr.processing {
  background-color: #f5e4e5 !important;
  border-left: 3px solid #9b2d35;
  position: relative;
}

tr.processing td:first-child {
  font-weight: 600;
  color: #9b2d35;
}

/* Home button */
.home-button .icon {
  transform: translateX(-2px); 
}

.table-container {
  min-height: 200px; 
  border: 1px solid var(--border-color);
  border-radius: 8px;
  flex: 1;
  overflow: hidden;
  position: relative;
}

.table-container.no-data {
  overflow: hidden; 
}

.empty-row td {
  height: 150px;
  vertical-align: middle;
  text-align: center;
}

.empty-message {
  color: var(--text-secondary);
  font-size: 0.95em;
}

.flat-stats-bar {
  display: flex;
  align-items: center;
  background: #f8f9fa;
  border-bottom: 1px solid #dee2e6;
  margin-bottom: -1px;
  width: 100%;
  min-height: 42px;
  overflow-x: auto;
}

.stat-cell {
  flex: 0 0 auto;
  padding: 8px 16px;
  border-right: 1px #dee2e6;
  min-width: 120px; 
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-number {
  font-size: 1.1em;
  font-weight: 600;
  color: #2c3e50;
  line-height: 1.2;
}

thead {
  position: sticky;
  top: 0;
  background: var(--bg-primary);
  z-index: 2;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
} 

table {
  width: 100%;
  border-collapse: collapse;
  background: white;
  position: relative;
  padding-top: 40px; 
}

th, td {
  border: 1px solid #ddd;
  white-space: pre-line;
  word-wrap: break-word;
  padding: 8px;
  text-align: left;
}

td {
  overflow: hidden;
  text-overflow:ellipsis;
}

th {
  color: #101010;
  background-color: #f4f4f4;
}

tr:hover {
  background: var(--color-background-mute);
}

.repo-filter-dropdown {
  position: absolute; /* 或者其他合适的定位方式 */
  background: white; /* 下拉菜单背景 */
  top: 100%; /* 使下拉菜单在表头下方 */
  left: 0;
  border-radius: 4px;
  border: 1px solid #ccc; /* 边框 */
  z-index: 1000; /* 确保在其他元素之上 */
}
.repo-filter-dropdown ul {
  list-style: none; /* 去掉默认的列表样式 */
  padding: 0; /* 去掉内边距 */
  margin: 0; /* 去掉外边距 */
}
.repo-filter-dropdown li {
  padding: 8px 12px; /* 添加内边距 */
  cursor: pointer; /* 鼠标悬停时显示为手指 */
}
.repo-filter-dropdown li:hover {
  background: #f0f0f0; /* 悬停时的背景颜色 */
}

.clickable {
  cursor: pointer; /* 鼠标悬停时显示为可点击 */
}

input {
  height: 30px;
}

.text-ellipsis {
  max-width: 150px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
