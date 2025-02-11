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
import { ref, onMounted } from 'vue';
import axios from 'axios';
import DataTable from './components/DataTable.vue';

export default {
  components: {
    DataTable,
  },
  setup() {
    const tableData = ref([]);
    const total = ref(0);
    const perPage = ref(20);
    const currentPage = ref(1);
    const searchQuery = ref('');

    const columns = ref(['name', 'base', 'repo', 'flag']);

    const fetchData = async (page = 1, search = '') => {
      try {
        const response = await axios.get('/api/packages/data', {
          params: {
            page,
            per_page: perPage.value,
            search,
          },
        });
        tableData.value = response.data.data;
        total.value = response.data.total;
      } catch (error) {
        console.error('Error fetching data:', error);
      }
    };

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
