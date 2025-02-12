<template>
  <div id="app">
    <DataTable
      :data="tableData"
      :columns="columns"
      :total="total"
      :perPage="perPage"
      @page-change="(data) => fetchData(data.page, data.search)"
      @search="handleSearch"
    />
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue';
import axios from 'axios';
import DataTable from './components/DataTable.vue';

export default {
  components: {
    DataTable,
  },
  setup() {
    const tableDataRaw = ref([]);
    const total = ref(0);
    const perPage = ref(20);
    const currentPage = ref(1);
    const searchQuery = ref('');

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
          'Could not resolv all dependencies',
          'Fail in prepare',
          'Fail in build',
          'Fail in check',
          'Fail in package',
          'Old config.guess'];
      // if x86 is 'N/A', but loong, testing or staging is not 'N/A', display 🗑
      if (!x86  && (loong || testing || staging )) {
          status = '🗑';
      }
      // if loong, testing and staging are all 'N/A', display ❌
      else if ((!loong) && (!testing) && (!staging)) {
          status = '❌';
      }
      // if loong and x86 matches, display ✅
      else if (compareVersions(loong, x86)) {
          status = '✅';
      }
      // if none of the versions are a match, but not 'N/A' either, display ⭕
      else {
          status = '⭕';
      }
      status += '&nbsp';
      if (flags) {
        if (flags & 1) status += `<span><a href="https://github.com/lcpu-club/loongarch-packages/tree/master/${item.base}" style="color: lime;" class="no-change">🅿</a></span>`; // has patch
        if (flags & 2) status += '<span style="color: blue;">🅲</span>'; // nocheck
        if (flags & 4) status += '<span style="color: orange;">🅾</span>'; // old config
        if (flags & 16) status += `<span><a href="log.html?url=/buildlogs/${item.base}/all.log" class="no-change" style="color: gold;">🅻</a></span>`; // has logs
        if (flags & (1 << 15)) status += `<span title="${fail_reason[(flags >> 16) - 1]}" style="cursor: pointer; color: red;">🅵</span>`
      }
      return status;
    }

    function mergeVersion(stable, testing, staging) {
      let merge = stable ? stable: 'N/A';
      if (testing) merge += `\n${testing}🄣`;
      if (staging) merge += `\n${staging}🄢`;
      return merge;
    }

    const fetchData = async (page = 1, search = '') => {
      try {
        const response = await axios.get('/api/packages/data', {
          params: {
            page,
            per_page: perPage.value,
            search,
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
        // Status: compareAll(item.x86_version, item.loong_version, item.loong_testing_version, item.loong_staging_version),
      }))
      );

    const handleSearch = (query) => {
      searchQuery.value = query;
      fetchData(1, query);
    };

    onMounted(() => {
      fetchData(currentPage.value, searchQuery.value);
    });

    return {
      tableData,
      columns,
      total,
      perPage,
      fetchData,
      handleSearch,
    };
  },
};
</script>

<style>
#app {
  width: 100%;
  font-family: Avenir, Helvetica, Arial, sans-serif;
  font-size: 16px;
  text-align: center;
  color: #2c3e50;
}
</style>
