<template>
  <div class="header-container">
    <div class="search-box">
      <input
        v-model="searchQuery"
        placeholder="Search..."
        @keyup.enter="onSearch"
      />
      <button @click="onSearch">Search</button>
      <div class="flags-filter">
        Filter Fails:
        <select v-model="selectedStatus" @change="onStatusChange">
          <option value="All">All</option>
          <option value="1">Fail to apply patch</option>
          <option value="2">Fail before build</option>
          <option value="3">Fail to download source</option>
          <option value="4">Fail to pass the validity check</option>
          <option value="5">Fail to pass PGP check</option>
          <option value="6">Could not resolve all dependencies</option>
          <option value="7">Fail in prepare</option>
          <option value="8">Fail in build</option>
          <option value="9">Fail in check</option>
          <option value="10">Fail in package</option>
          <option value="11">Old config.guess</option>
        </select>
      </div>
    </div>
    <div class="paginator">
      <button @click="prevPage" :disabled="currentPage === 1">Previous</button>
      <span>Page {{ currentPage }} of {{ totalPages }}</span>
      <button @click="nextPage" :disabled="currentPage >= totalPages">Next</button>
      <input
        v-model.number="goToPage"
        type="number"
        min="1"
        :max="totalPages"
        @keyup.enter="goToSpecificPage"
      />
      <button @click="goToSpecificPage">Go</button>
    </div>
    <div class="legend">
      <span>Status Legend:</span>
      <span title="loong's version matches x86's">✅</span>
      <span title="loong's version mis-matches">⭕</span>
      <span title="missing this package in loong">❌</span>
      <span title="missing this package in x86">🗑</span>
      <span title="has patch in our repo" style="color: lime;">🅿</span>
      <span title="has build log on server" style="color: gold;">🅻</span>
      <span title="build with nocheck" style="color: blue;">🅲</span>
      <span title="config.sub is too old" style="color: orange;">🅾</span>
      <span title="build fails" style="color: red;">🅵</span>
    </div>
  </div>
  <div class="table-container">
    <table>
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in tableData" :key="row.id">
          <td v-for="column in columns" :key="column" v-html="row[column]"></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script>
import { useRoute } from 'vue-router';
import { ref, computed, onMounted } from 'vue';
import axios from 'axios';

export default {
  setup() {
    const tableDataRaw = ref([]);
    const total = ref(0);
    const perPage = ref(20);
    const currentPage = ref(1);
    const searchQuery = ref('');
    const goToPage = ref(1);
    const selectedStatus = ref('');
    const route = useRoute();

    const columns = ref(['Name', 'Base', 'Repo', 'x86 Version', 'Loong Version', 'Status']);

    function compareVersions(loongVersion, x86Version) {
      if (!loongVersion || !x86Version) return false;
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
      let flags = item.flags;
      let status;
      const fail_reason = ['Fail to apply patch',
          'Fail before build',
          'Fail to download source',
          'Fail to pass the validity check',
          'Fail to pass PGP check',
          'Could not resolve all dependencies',
          'Fail in prepare',
          'Fail in build',
          'Fail in check',
          'Fail in package',
          'Old config.guess'];

      if (!x86  && (loong || testing || staging )) {
          status = '🗑';
      } else if ((!loong) && (!testing) && (!staging)) {
          status = '❌';
      } else if (compareVersions(loong, x86)) {
          status = '✅';
      } else {
          status = '⭕';
      }

      status += '&nbsp';
      if (flags) {
        if (flags & 1) status += `<span><a href="https://github.com/lcpu-club/loongarch-packages/tree/master/${item.base}" style="color: lime;">🅿</a></span>`;
        if (flags & 2) status += '<span style="color: blue;">🅲</span>';
        if (flags & 4) status += '<span style="color: orange;">🅾</span>';
        if (flags & 16) status += `<span><a href="log.html?url=/buildlogs/${item.base}/all.log" style="color: gold;">🅻</a></span>`;
        if (flags & (1 << 15)) status += `<span title="${fail_reason[flags >> 16 - 1]}" style="cursor: pointer; color: red;">🅵</span>`;
      }
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
            search: searchQuery.value,
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
        'x86 Version': mergeVersion(item.x86_version, item.x86_testing_version, item.x86_staging_version),
        'Loong Version': mergeVersion(item.loong_version, item.loong_testing_version, item.loong_staging_version),
        Status: compareAll(item),
      }))
    );

    const nextPage = () => {
      if (currentPage.value < totalPages.value) {
        currentPage.value++;
        fetchData();
      }
    };

    const prevPage = () => {
      if (currentPage.value > 1) {
        currentPage.value--;
        fetchData();
      }
    };

    const goToSpecificPage = () => {
      if (goToPage.value >= 1 && goToPage.value <= totalPages.value) {
        currentPage.value = goToPage.value;
        fetchData();
      }
    };

    const totalPages = computed(() => Math.ceil(total.value / perPage.value));

    onMounted(() => {
      if (route.query.search) {
        searchQuery.value = route.query.search;
      }
      fetchData();
    });

    const onStatusChange = () => {
      if (selectedStatus.value === 'All') {
        searchQuery.value = ':fail';
      } else {
        searchQuery.value = `:code${selectedStatus.value}`;
      }
      onSearch();
    };

    const onSearch = () => {
      currentPage.value = 1;
      if (!searchQuery.value.startsWith(':')) {
        selectedStatus.value = '';
      }
      fetchData();
    };

    return {
      tableData,
      columns,
      totalPages,
      currentPage,
      searchQuery,
      goToPage,
      fetchData,
      nextPage,
      prevPage,
      goToSpecificPage,
      selectedStatus,
      onStatusChange,
      onSearch,
    };
  },
};
</script>
<style scoped>
.table-container {
  width: 100%;
  margin-top: 10px;
  overflow-x: auto;
}

.header-container {
  width: 100%;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between; /* Aligns left and right */
  align-items: center; /* Vertically center items */
}

.search-box {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  display: flex;
  gap: 10px; /* Adds spacing between input and button */
}

.legend {
  display: flex;
  gap: 10px;
}

.paginator {
  align-items: center;
  display: flex;
  gap: 10px;
}

table {
  width: 100%;
  border-collapse: collapse;
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

input {
  height: 30px;
}
</style>
